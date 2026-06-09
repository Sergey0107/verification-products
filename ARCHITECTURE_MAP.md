# Архитектурная карта бэкенда `app/`

Дата актуализации: 2026-06-04.

Бэкенд `ivolga` — это набор FastAPI‑микросервисов, оркестрируемых через
Docker Compose. Сценарий продукта: пользователь загружает два документа
(**ТЗ** — техническое задание и **паспорт** изделия), система извлекает из них
характеристики с помощью LLM, даёт пользователю проверить характеристики ТЗ,
а затем сравнивает ТЗ с паспортом и показывает таблицу совпадений с
привязкой к исходному PDF.

> Frontend (`pdf-analyzer`) и сервис извлечения (`extraction`) лежат в
> соседних репозиториях и в этой карте описаны только как внешние границы.

---

## 1. Сервисы и их зоны ответственности

| Сервис | Порт | Стек | За что отвечает |
|--------|------|------|-----------------|
| **api-gateway** | 8000 | FastAPI + SQLAlchemy (async) + Celery | Единая точка входа. Аутентификация (сессии + CSRF), авторизация, проксирование файлов, оркестрация пайплайна анализа, REST API для фронтенда. |
| **file-service** | 8001 | FastAPI + Celery + boto3 | Приём файлов, заливка в S3/MinIO, выдача presigned‑URL, рендер превью (PDF напрямую, Word → PDF через LibreOffice). |
| **prompt-registry** | 8002 | FastAPI | Версионированное хранилище промптов и JSON‑схем для извлечения (`tz`, `passport`, `comparison`). |
| **domain-analyze** | 8003 | FastAPI + Celery | Сравнение характеристик ТЗ и паспорта через LLM, формирование таблицы совпадений. |
| **knowledge-base** | 8004 | FastAPI + pgvector | База канонических атрибутов и нормативных выдержек; семантический поиск (RAG‑контекст для извлечения и сравнения). |
| **extraction** *(внешний)* | 8005 | FastAPI + PyMuPDF | Извлечение структуры из документа через OpenRouter/LlamaParse, геометрическая привязка цитат; рендер PDF. |

### Инфраструктура

| Компонент | Назначение |
|-----------|------------|
| **PostgreSQL** (`pgvector/pgvector:pg15`) | Общая БД. Логически разделена по схемам: `users`, `analysis`, `files`, `knowledge`. Каждый сервис владеет своими таблицами. |
| **RabbitMQ** | Брокер Celery. Очереди именованы по сервисам: `api_gateway`, `file_service`, `domain_analyze`. |
| **MinIO** | S3‑совместимое объектное хранилище для документов (в продакшене — Yandex Object Storage). |

Каждый сервис, использующий Celery, поднимается в двух ролях: HTTP‑сервер
(`uvicorn`) и worker (`celery ... worker -Q <очередь>`) — это видно в
`docker-compose.yml`.

---

## 2. Топология

```text
                         ┌────────────────┐
        браузер ───────► │  api-gateway   │ ◄──── единственный публичный вход
       (pdf-analyzer)    │   :8000        │       (auth-gate middleware)
                         └───────┬────────┘
            ┌────────────────────┼─────────────────────┬──────────────┐
            ▼                    ▼                     ▼              ▼
     ┌────────────┐      ┌──────────────┐      ┌──────────────┐  ┌──────────┐
     │file-service│      │prompt-registry│      │domain-analyze│  │knowledge │
     │   :8001    │      │    :8002      │      │    :8003     │  │  -base   │
     └─────┬──────┘      └──────────────┘      └──────┬───────┘  │  :8004   │
           │                                          │          └────┬─────┘
           ▼                                          ▼               │
       ┌───────┐                            ┌──────────────┐          │
       │ MinIO │                            │  extraction  │          │
       │  /S3  │                            │    :8005     │          │
       └───────┘                            └──────────────┘          │
                                                                      ▼
     ┌──────────────────────── PostgreSQL (pgvector) ───────────────────┐
     │  schema users  │  schema analysis  │  schema files │ schema knowledge│
     └──────────────────────────────────────────────────────────────────┘

           RabbitMQ ── очереди: api_gateway · file_service · domain_analyze
```

Связь между сервисами — двух видов:

1. **Синхронный HTTP** (httpx) — когда нужен немедленный ответ
   (получить промпт, presigned‑URL, выполнить извлечение).
2. **Асинхронный Celery + callback** — для долгих задач. Producer ставит
   задачу в очередь и сразу отвечает; worker по завершении дёргает
   `*/callback`‑эндпоинт api-gateway, который двигает статус анализа.

---

## 3. Сквозной поток (happy path)

```text
1. upload         POST /files/upload  (api-gateway)
                  └─ создаёт Analysis(status=processing_files) + 2×File
                  └─ стримит файлы в file-service /files/upload-batch
                       └─ Celery file_service: заливка в S3 → /files/callback

2. files callback POST /files/callback  (api-gateway)
                  └─ когда оба файла uploaded → status=extracting_data
                  └─ ставит ExtractionJob(tz) → Celery api_gateway.extract_file

3. extract TZ     api-gateway worker → extraction-service /extract
                  (промпт берётся из prompt-registry, контекст — из knowledge-base)
                  └─ сохраняет ExtractionResult(tz) → status=tz_review

4. TZ review      GET/PUT /api/analyses/{id}/tz-review  (пользователь правит)
                  POST .../tz-review/continue
                  └─ ставит ExtractionJob(passport) с одобренными характеристиками

5. extract PASS   api-gateway worker → extraction-service /extract
                  └─ ExtractionResult(passport) → status=analyzing_data
                  └─ создаёт ComparisonJob → domain-analyze /compare/jobs

6. compare        domain-analyze worker → LLM сравнение ТЗ vs паспорт
                  └─ POST /compare/callback (api-gateway)
                       └─ пишет ComparisonRow[] → status=ready

7. viewer         GET /api/analyses/{id}/viewer-context
                  └─ строки сравнения + evidence (цитаты/страницы для подсветки)
```

Машина состояний `Analysis.status`:

```
processing_files → extracting_data → tz_review → extracting_passport
   → analyzing_data → ready
                          └──────────► failed  (на любом шаге при ошибке)
```

Маппинг статусов в человекочитаемые лейблы и UI‑ключи (`in-progress` /
`review` / `ready` / `error`) живёт в `api/analyses.py`
(`_status_label`, `_status_key`).

---

## 4. Внутреннее устройство api-gateway

```text
app/
  main.py                 — сборка FastAPI, подключение роутеров, auth-gate middleware
  api/
    auth.py               — register/login/logout, сессии, CSRF, get_current_user
    deps.py               — общие зависимости (parse_uuid)
    files.py              — upload / download / preview, callback от file-service
    analyses.py           — список анализов, TZ-review, extraction/comparison, viewer-context
    comparison_rows.py    — правки пользователя по строкам сравнения
    compare.py            — callback от domain-analyze
    health.py             — health-проба + проба file-service
  core/
    config.py             — pydantic Settings (env-driven)
    security.py           — argon2-хэширование паролей, токены сессий/CSRF
  db/
    base.py               — Declarative Base
    session.py            — async engine/session (для HTTP-обработчиков)
    session_sync.py       — sync engine/session (для Celery-воркеров)
    models/               — ORM-модели по схемам БД
  services/
    extraction_tasks.py   — сборка промпта + вызов extraction-service
    extraction_jobs.py    — переходы статусов ExtractionJob
    extraction_backends.py— нормализация выбора бэкенда (openrouter/llamaparse)
    knowledge_base_client.py — HTTP-клиент к knowledge-base
    comp_data.py          — дамп результатов на диск (отладка/совместимость)
  tasks.py                — Celery-задача extract_file (оркестрация пайплайна)
  celery_app.py           — конфигурация Celery
  migration/              — Alembic (источник истины по схеме БД)
```

**Ключевой момент — два слоя доступа к БД.** HTTP‑обработчики работают через
**async** SQLAlchemy (`db/session.py`, `asyncpg`). Celery‑воркеры синхронны,
поэтому используют отдельный **sync**‑движок (`db/session_sync.py`,
`psycopg2`); URL автоматически переписывается с `+asyncpg` на `+psycopg2`.
Смешивать их нельзя — это сознательное разделение.

**Безопасность (`auth.py` + `main.py`).**
- Сессии — opaque‑токены в httpOnly‑cookie; в БД хранится только SHA‑256‑хэш.
- Защита от CSRF — double‑submit: токен лежит и в нечитаемой для JS cookie,
  и должен прийти в заголовке `X-CSRF-Token` для небезопасных методов.
- `auth_gate` middleware закрывает всё, кроме явного allow‑list
  (`/health`, `/auth/login`, `/docs`, callback’и и т. п.), и проверяет CSRF
  централизованно.

---

## 5. Прочие сервисы — кратко

- **file-service** — конвертацию Word → PDF делает LibreOffice (`soffice
  --headless`) в изолированном профиле; presigned‑URL обновляются по запросу,
  чтобы обойти TTL ссылок.
- **prompt-registry** — отдаёт `{prompt, schema}` по типу документа; промпты
  версионированы в `services/prompt_store.py`.
- **domain-analyze** — берёт промпт сравнения из prompt-registry, обогащает
  контекст из knowledge-base, парсит JSON‑ответ LLM (устойчиво к ```‑обёрткам);
  при ошибке прокидывает `raw` ответ в callback для диагностики.
- **knowledge-base** — единственный владелец схемы `knowledge`; на старте
  создаёт схему и (опционально) загружает данные; векторный поиск через
  pgvector. Канонические атрибуты используются как словарь синонимов при
  извлечении из паспорта.

---

## 6. Конфигурация и инварианты

- Вся конфигурация — через переменные окружения (`env/.env`), читается
  pydantic‑классами `Settings`. Хардкодов адресов сервисов в коде быть не
  должно — только `settings.*_URL`.
- Межсервисные URL фиксированы DNS‑именами Docker Compose
  (`http://file-service:8000` и т. д.).
- Источник истины по схеме БД — **миграции Alembic**, а не `create_all`.
  Контейнер api-gateway на старте ждёт БД и прогоняет `alembic upgrade head`.
- Celery‑задачи идемпотентны по `task_id` (используется id job’а), что
  защищает от дублей при ретраях; все долгие задачи имеют
  `autoretry_for=(Exception,)` с экспоненциальным backoff.

---

## 7. Полный жизненный цикл разбора документов

Ниже — сквозной воркфлоу одного анализа: от входа пользователя до
результирующей таблицы совпадений. Каждый шаг помечен сервисом‑владельцем
и переходом статуса `Analysis.status` (если он меняется).

### 7.0. Аутентификация (вход в систему)

```text
POST /auth/login {login, password}                         [api-gateway]
  ├─ verify_password (argon2) против users.user.password_hash
  ├─ create_user_session:
  │    session_token, csrf_token = два случайных токена (token_urlsafe)
  │    в БД (users.session) кладётся только их SHA-256-хэш
  ├─ Set-Cookie: ivolga_session (httpOnly)  ← браузер не читает
  │  Set-Cookie: ivolga_csrf    (JS-readable)
  └─ ответ: {user, csrf_token}

Далее каждый запрос проходит auth_gate (middleware):
  ├─ путь в ALLOWED_PATHS?  → пропустить (login, health, docs, callbacks)
  ├─ найти юзера по хэшу session-cookie (не истёк, не отозван)
  ├─ для POST/PUT/PATCH/DELETE: double-submit CSRF
  │    cookie ivolga_csrf == header X-CSRF-Token  И  совпадает с хэшем в БД
  └─ нет юзера → 401
```

### 7.1. Загрузка и заливка файлов

```text
POST /files/upload (multipart: tz_file, passport_file,        [api-gateway]
                    extraction_backend, task_id, product_model)
  ├─ Analysis(status=processing_files) + 2×File(status=uploading)   ─┐
  └─ стрим обоих файлов → file-service /files/upload-batch           │ status:
                                                                     │ processing_files
POST /files/upload-batch                                [file-service] │
  ├─ пишет файлы во временный каталог
  └─ 2× Celery (file_service): upload_to_s3.delay(...)
        ├─ заливка в S3/MinIO
        └─ POST /files/callback {file_id, status=uploaded, url, ...}  → api-gateway
```

### 7.2. Извлечение ТЗ

```text
POST /files/callback (по каждому файлу)                       [api-gateway]
  ├─ File.status = uploaded
  └─ когда ОБА файла uploaded:                              status: extracting_data
        ├─ Analysis.status = extracting_data
        ├─ создаёт ExtractionJob(tz, status=queued)
        └─ Celery api_gateway.extract_file.apply_async(... task_id=job_id)

extract_file (worker)                              [api-gateway worker]
  └─ run_extraction_task:
        ├─ presigned-URL у file-service /files/presign (свежий, TTL обходится)
        ├─ промпт+схема у prompt-registry /prompts/tz
        ├─ обогащение промпта из knowledge-base (единицы измерения; для ТЗ
        │   названия НЕ нормализуются — берутся дословно)
        └─ POST extraction-service /extract {file_url, prompt, schema, backend}
              └─ (детали внутри — см. 7.5)
        ⇒ ExtractionResult(tz, payload)             status: tz_review
```

### 7.3. Проверка характеристик ТЗ пользователем

```text
GET  /api/analyses/{id}/tz-review        → характеристики ТЗ + документ для viewer
PUT  /api/analyses/{id}/tz-review        → сохранить approved/comment по каждой
POST /api/analyses/{id}/tz-review/continue                   [api-gateway]
  ├─ требуется ≥1 одобренная характеристика
  ├─ из payload ТЗ достаётся product_model (или из Analysis от пользователя)
  ├─ ExtractionJob(passport, status=queued) с одобренными
  │   характеристиками как target_characteristics
  └─ Celery extract_file(...)                       status: extracting_passport
```

Это единственная ручная точка в пайплайне — остальное автоматическое.

### 7.4. Извлечение паспорта и запуск сравнения

```text
extract_file (passport)                            [api-gateway worker]
  └─ run_extraction_task → extraction-service /extract
        (для паспорта промпт обогащается синонимами из knowledge-base и
         списком целевых характеристик ТЗ + моделью изделия)
  ⇒ ExtractionResult(passport)
  └─ т.к. file_type == passport и есть одобренные характеристики ТЗ:
        ├─ ComparisonJob(status=queued)            status: analyzing_data
        └─ POST domain-analyze /compare/jobs {tz_data(filtered), passport_data}

compare_documents (worker)                         [domain-analyze worker]
  ├─ промпт сравнения из prompt-registry /prompts/comparison
  ├─ контекст из knowledge-base (канонические атрибуты, синонимы)
  ├─ LLM сравнивает характеристику ТЗ ↔ паспорта, устойчивый парсинг JSON
  └─ finally: POST /compare/callback {status, result | error, raw}  → api-gateway
```

### 7.5. Что происходит внутри extraction-service (`/extract`)

```text
POST /extract {file_url, prompt, schema, backend}            [extraction]
  ├─ _select_backend → openrouter (по умолчанию) | llamaparse
  │     (docling_local / docling_remote — заглушки, отдают 501)
  │
  ├─ _download_file(file_url) → временный файл + content_type
  ├─ детекция типа: _looks_like_{pdf,docx,image}
  │
  ├─ путь "текст" (надёжнее file-parser плагина):
  │     DOCX → _convert_docx_to_structured_text (python-docx)
  │     PDF  → _convert_pdf_to_structured_text (текстовый слой; если пусто —
  │            Tesseract OCR через PyMuPDF)
  │
  ├─ сборка messages + JSON-schema response_format
  │     ⇒ POST OpenRouter /chat/completions (temperature=0)
  │        ├─ при отказе по response_format — fallback без него
  │        └─ при несоответствии схеме — _repair_json_to_schema (повторный LLM)
  │
  ├─ _normalize_references_in_place (модели иногда дают dict вместо list)
  │
  └─ геометрическая привязка (если GEOMETRY_ENRICHMENT_ENABLED и PyMuPDF):
        DOCX → сначала конвертация в PDF (LibreOffice) для координат
        _enrich_references_with_pdf_geometry:
          для каждой references-цитаты ищем её позицию в PDF —
          точный поиск → токенный → поиск по строке таблицы → OCR-fallback,
          ранжируем кандидатов, пишем bbox + page_number в evidence
  ⇒ {result, extraction:{pages}, extraction_metadata:{geometry, usage, ...}}
```

Именно геометрия даёт фронтенду координаты для подсветки цитаты прямо в PDF.

### 7.6. Сборка результирующей таблицы

```text
POST /compare/callback {status=succeeded, result}            [api-gateway]
  ├─ ComparisonJob.result = result
  ├─ удаляет старые ComparisonRow, пишет новые из result.comparisons:
  │     characteristic, tz_value, passport_value, llm_result(is_match),
  │     tz_evidence, passport_evidence, note
  ├─ Analysis.status = ready
  └─ update_comp_data — дамп на диск (отладка/совместимость)

GET /api/analyses/{id}/viewer-context                        [api-gateway]
  ⇒ строки сравнения + документы + evidence (цитаты/страницы/bbox) +
    пользовательские комментарии (UserEdit + TzCharacteristicReview)
  → фронтенд рисует таблицу совпадений и подсветку в PDF-вьювере

Пользователь может скорректировать вердикт:
  POST /api/comparison-rows/{row_id}/user-result {user_result}
  POST /api/comparison-rows/{row_id}/comment    {comment}
```

### 7.7. Диаграмма всего пути

```text
 [user] login ─► auth_gate ─► upload ─► S3
                                  │
                          extract TZ ──► extraction-service ──► LLM + geometry
                                  │            (prompt-registry, knowledge-base)
                          ◄ tz_review (ручная проверка) ─ [user]
                                  │
                          extract PASSPORT ─► extraction-service ──► LLM + geometry
                                  │
                          compare ─► domain-analyze ──► LLM (prompt-registry, KB)
                                  │
                          ComparisonRow[] ─► viewer-context ─► [user] таблица + PDF
```

---

## 8. Сервис extraction (внешний репозиторий)

Хотя `extraction` лежит в отдельном репозитории, он — ключевое звено
пайплайна, поэтому описан здесь. После рефакторинга его модули:

| Модуль | Назначение |
|--------|------------|
| `app/config.py` | Все env‑константы + проба опциональных зависимостей (PyMuPDF, Docling) с флагами `*_INSTALLED`. |
| `app/models.py` | `ExtractionRequest` (Pydantic) и внутренние dataclass’ы (`DownloadedFile`, `PdfWord`, `PdfPageIndex`). |
| `app/schema_utils.py` | Интерпретация JSON Schema → шаблон, нормализация схемы. |
| `app/main.py` | FastAPI‑приложение, маршруты `/extract` и `/render-pdf`, бэкенды (OpenRouter, LlamaParse), геометрическая привязка через PyMuPDF. |

Инварианты:
- Бэкенды `docling_*` намеренно оставлены заглушками (`501`) «на будущее».
- `/render-pdf` растеризует PDF постранично (PyMuPDF) — обходит проблему
  нестандартных кириллических шрифтов, которые PDF.js не отображает.
- Тяжёлые зависимости опциональны: при их отсутствии сервис не падает на
  импорте, а деградирует (геометрия/render отключаются).
