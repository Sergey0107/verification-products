import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.knowledge_base_client import list_canonical_attributes, search_knowledge

logger = logging.getLogger(__name__)
MAX_ERROR_BODY_LENGTH = 2000


def _response_error_text(response: httpx.Response, service_name: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = (response.text or "").strip()
    else:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if detail is not None:
                text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
            else:
                text = json.dumps(payload, ensure_ascii=False)
        else:
            text = json.dumps(payload, ensure_ascii=False)

    text = (text or "").strip()
    if len(text) > MAX_ERROR_BODY_LENGTH:
        text = f"{text[:MAX_ERROR_BODY_LENGTH]}..."
    return text or f"{service_name} returned HTTP {response.status_code}"


def _raise_for_status_with_detail(response: httpx.Response, service_name: str) -> None:
    if response.is_success:
        return

    detail = _response_error_text(response, service_name)
    logger.error(
        "%s request failed: status=%s url=%s detail=%s",
        service_name,
        response.status_code,
        response.request.url,
        detail,
    )
    message = f"{service_name} HTTP {response.status_code}: {detail}"
    raise httpx.HTTPStatusError(message, request=response.request, response=response)


def _collect_products_from_extracted_data(extracted_data: object) -> list[dict]:
    if isinstance(extracted_data, dict):
        products = extracted_data.get("products")
        if isinstance(products, list):
            return [item for item in products if isinstance(item, dict)]
        if any(
            key in extracted_data
            for key in ("product_name", "product_model", "characteristics")
        ):
            return [extracted_data]
        return []
    if isinstance(extracted_data, list):
        return [item for item in extracted_data if isinstance(item, dict)]
    return []


def _dedupe_products(products: list[dict]) -> list[dict]:
    seen: set[tuple[object, object]] = set()
    unique: list[dict] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        key = (product.get("product_name"), product.get("product_model"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique


def _normalize_docling_extraction(result_payload: dict) -> None:
    if not isinstance(result_payload, dict):
        return
    extraction = result_payload.get("extraction")
    if not isinstance(extraction, dict):
        return
    pages = extraction.get("pages")
    if not isinstance(pages, list):
        return
    if isinstance(extraction.get("products"), list):
        return
    products: list[dict] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        products.extend(
            _collect_products_from_extracted_data(page.get("extracted_data"))
        )
    extraction["products"] = _dedupe_products(products)


def _looks_like_characteristic(item: object) -> bool:
    """Элемент products — это «плоская» характеристика (name+value),
    а не изделие (нет вложенного characteristics)."""
    if not isinstance(item, dict):
        return False
    if isinstance(item.get("characteristics"), list):
        return False
    has_name = isinstance(item.get("name"), str) and item.get("name").strip()
    has_value = "value" in item
    return bool(has_name and has_value)


def _wrap_flat_products(products: list) -> list:
    """Некоторые модели возвращают products как ПЛОСКИЙ список характеристик
    (каждый элемент — name+value), вместо вложенной структуры
    products[i].characteristics[]. Тогда характеристики «теряются» (парсер ищет
    .characteristics и находит 0). Оборачиваем плоский список в одно изделие."""
    if not isinstance(products, list) or not products:
        return products
    flat = [p for p in products if _looks_like_characteristic(p)]
    # Считаем формат плоским, только если БОЛЬШИНСТВО элементов — характеристики,
    # и ни у одного нет вложенного characteristics (иначе это смешанный/нормальный).
    if len(flat) >= max(1, len(products) // 2) and not any(
        isinstance(p, dict) and isinstance(p.get("characteristics"), list)
        for p in products
    ):
        # Берём название/модель из первого элемента, если он их содержит
        product_name = None
        product_model = None
        for p in products:
            if isinstance(p, dict):
                product_name = product_name or p.get("product_name")
                product_model = product_model or p.get("product_model")
        return [
            {
                "product_name": product_name,
                "product_model": product_model,
                "characteristics": flat,
            }
        ]
    return products


def _normalize_flat_products_in_place(result_payload: dict) -> bool:
    """Оборачивает плоский список характеристик в изделие. Возвращает True, если
    нормализация применена. Чинит result.products, extraction.products И
    extraction.pages[].extracted_data.products — последнее важно, потому что
    extraction.products собирается ИЗ pages, и если pages остаются плоскими,
    собранный extraction.products получается из «изделий» с пустыми характеристиками."""
    if not isinstance(result_payload, dict):
        return False
    applied = False

    def _fix_products_holder(holder: dict) -> None:
        nonlocal applied
        if isinstance(holder, dict) and isinstance(holder.get("products"), list):
            wrapped = _wrap_flat_products(holder["products"])
            if wrapped is not holder["products"] and wrapped != holder["products"]:
                holder["products"] = wrapped
                applied = True

    for root_key in ("result", "extraction"):
        root = result_payload.get(root_key)
        if isinstance(root, dict):
            _fix_products_holder(root)

    # Чиним вложенные pages[].extracted_data до сборки extraction.products.
    extraction = result_payload.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("pages"), list):
        for page in extraction["pages"]:
            if isinstance(page, dict) and isinstance(page.get("extracted_data"), dict):
                _fix_products_holder(page["extracted_data"])

    return applied


def _build_knowledge_base_prompt_appendix(file_type: str) -> str:
    if file_type not in {"tz", "passport"}:
        return ""

    sections: list[str] = []

    # Для ТЗ Knowledge Base используем только как справочник единиц измерения —
    # названия характеристик берём дословно из документа, без нормализации.
    # Для паспорта — добавляем синонимы, чтобы найти характеристику под другим названием.
    if file_type == "passport":
        try:
            attributes = list_canonical_attributes()
        except Exception:
            attributes = []
        if attributes:
            lines = ["Канонические технические атрибуты из Knowledge Base (используй для поиска по синонимам):"]
            for item in attributes[:100]:
                name = item.get("name")
                normalized_name = item.get("normalized_name")
                unit = item.get("unit")
                synonyms = ", ".join(str(v) for v in (item.get("synonyms") or [])[:8])
                lines.append(
                    f"- name={name}; normalized_name={normalized_name}; unit={unit}; synonyms={synonyms}"
                )
            sections.append("\n".join(lines))

    try:
        retrieval = search_knowledge(
            "технические характеристики оборудования паспорт изделия техническое задание соответствие параметры требования",
            limit=5,
        )
    except Exception:
        retrieval = []
    if retrieval:
        lines = ["Релевантные нормативные/методические выдержки из Knowledge Base:"]
        for item in retrieval:
            lines.append(
                f"- [{item.get('source_key')} v{item.get('source_version')}] {item.get('source_title')}: {item.get('text')}"
            )
        sections.append("\n".join(lines))

    if not sections:
        return ""

    if file_type == "passport":
        prefix = "\n\nИспользуй следующую Knowledge Base как источник истины для нормализации характеристик и терминов:\n"
    else:
        # Для ТЗ: НЕ нормализуем названия — берём дословно из документа
        prefix = "\n\nДополнительный контекст из Knowledge Base (только для справки, НЕ используй для переименования характеристик — названия бери дословно из документа):\n"

    return prefix + "\n\n".join(sections)


def _build_product_model_appendix(file_type: str, product_model: str | None) -> str:
    """Если указана модель изделия — добавляем инструкцию LLM искать характеристики только для неё."""
    if not product_model or file_type != "tz":
        return ""
    return (
        f"\n\nIMPORTANT: The document may contain specifications for multiple product models. "
        f"Extract characteristics ONLY for model '{product_model}'. "
        f"If the document has a table with columns for different models, use only the column "
        f"that corresponds to '{product_model}'. Do not take values from other model columns. "
        f"If the model '{product_model}' is not found in the document, extract the closest match "
        f"and note that the exact model was not found.\n"
    )


def _model_size_cores(product_model: str) -> list[str]:
    """Извлекает числовое ядро типоразмера — самую стабильную часть кода модели
    между ТЗ и паспортом. Префиксы (5Кс / КС / 1Кс) и исполнение (/4) различаются
    от документа к документу, а ядро «подача-напор» совпадает точно.
    '5Кс — 5х4 (КС 50-110/4)' → ['50-110/4', '50-110'] ; '1Кс50-110' → ['50-110']."""
    norm = (
        product_model.lower()
        .replace("ё", "е")
        .replace("–", "-")
        .replace("—", "-")
        .replace("х", "x")
    )
    cores: list[str] = []
    for match in re.findall(r"\d+(?:[-/x]\d+)+", norm):
        if match not in cores:
            cores.append(match)
        # Основа без хвостового исполнения: 50-110/4 → 50-110
        base = match.split("/", 1)[0]
        if "-" in base and base not in cores:
            cores.append(base)
    # Сортируем по длине убыв.: более специфичные ядра (50-110/4) раньше общих (50-110)
    return sorted(cores, key=len, reverse=True)


def _model_aliases(product_model: str) -> list[str]:
    """Разбивает составной код модели на отдельные распознаваемые варианты.
    '5Кс — 5х4 (КС 50-110/4)' → ['5Кс — 5х4 (КС 50-110/4)', 'КС 50-110/4', '5Кс — 5х4', '50-110/4', '50-110'].
    Паспорт обычно использует один из вариантов (часто только числовое ядро)."""
    aliases: list[str] = [product_model.strip()]
    # Коды в скобках — частый альтернативный шифр модели.
    for match in re.findall(r"\(([^)]+)\)", product_model):
        cleaned = match.strip()
        if cleaned and cleaned not in aliases:
            aliases.append(cleaned)
    # Часть до скобки — основной шифр.
    before_paren = re.sub(r"\([^)]*\)", "", product_model).strip(" —-–")
    if before_paren and before_paren not in aliases:
        aliases.append(before_paren)
    # Числовое ядро типоразмера — самый устойчивый идентификатор между документами.
    for core in _model_size_cores(product_model):
        if core not in aliases:
            aliases.append(core)
    return [a for a in aliases if a]


def _build_target_characteristics_appendix(
    file_type: str,
    target_characteristics: list[dict] | None,
) -> str:
    if file_type != "passport" or not target_characteristics:
        return ""

    # ВАЖНО: НЕ передаём в паспорт значения из ТЗ (item["value"]).
    # Если показать модели ожидаемое значение, она копирует его вместо чтения
    # паспорта — паспортные значения получались равными ТЗ байт-в-байт, даже когда
    # в реальном паспорте стояли другие числа. Передаём ТОЛЬКО названия характеристик.
    target_names: list[str] = []
    product_model: str | None = None
    product_name: str | None = None
    for item in target_characteristics:
        if not isinstance(item, dict):
            continue
        if not product_model:
            product_model = item.get("product_model")
        if not product_name:
            product_name = item.get("product_name")
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            target_names.append(name.strip())
    if not target_names:
        return ""

    targets_json = json.dumps(target_names, ensure_ascii=False, indent=2)

    # Формируем подсказку о модели для точного поиска в многоколоночных/многострочных
    # таблицах. Отдельно разбираем габаритные размеры — они часто лежат в отдельной
    # таблице с краткими заголовками (L/H/W) и берутся не из той строки модели.
    model_hint = ""
    if product_model:
        model_aliases = _model_aliases(product_model)
        aliases_text = (
            f" Equivalent model codes to recognise: {', '.join(repr(a) for a in model_aliases)}."
            if len(model_aliases) > 1
            else ""
        )
        size_cores = _model_size_cores(product_model)
        core_hint = ""
        if size_cores:
            core_hint = (
                f"\n- KEY IDENTIFIER — the numeric size code (типоразмер) {', '.join(repr(c) for c in size_cores)} "
                f"is the MOST RELIABLE way to find the model. The LETTER PREFIX often differs between "
                f"documents (e.g. requirement says 'КС 50-110/4' but the passport writes the SAME pump "
                f"as '1Кс50-110' or '5Кс50-110') — match by the numeric core '{size_cores[0].split('/')[0]}' "
                f"and IGNORE prefix/suffix differences. A passport row whose code contains '{size_cores[0].split('/')[0]}' "
                f"is the right one even if its prefix is not identical.\n"
            )
        model_hint = (
            f"\nIMPORTANT — MODEL SELECTION. The passport usually lists MANY models. "
            f"Extract values strictly for model '{product_model}'"
            + (f" (product: '{product_name}')" if product_name else "")
            + "."
            + aliases_text
            + core_hint
            + " Rules for model-keyed tables:\n"
            f"- ALL extracted values MUST come from the SAME model row/column. "
            f"It is a serious error to take Производительность from one model and Вес from another — "
            f"every characteristic must describe the SAME physical pump '{product_model}'.\n"
            f"- A value belongs to the model written ON THE SAME ROW (or in the SAME COLUMN). "
            f"Do NOT take the value from a neighbouring model's row/column — values for "
            f"adjacent models often look similar, so align the row to '{product_model}' EXACTLY.\n"
            f"- Match the model code allowing spacing/separator/prefix differences "
            f"(e.g. 'ХМ-3,2/4Т-0.18-G1' == 'ХМ 3,2/4Т-0,18-G1'; 'КС 50-110/4' == '1Кс50-110').\n"
            "- DIMENSIONS (Габаритные размеры / габариты): these are frequently in a SEPARATE "
            "table whose columns use short headers like 'L', 'B', 'H', 'L1', 'B1', etc. "
            "Find the EXACT row matching the target model in THAT table and take L, B (or W/Ширина), "
            "H values from THAT SINGLE ROW. Never mix values from different rows — e.g. do NOT "
            "take L from row '1Кс12-50' and H from row '1Кс20-110'. If the target model is not in "
            "the table, return null.\n"
            "- WEIGHT (Вес / Масса): the dimensions table often has a 'Масса, кг' column — this "
            "is the catalog mass for a SPECIFIC model variant, NOT the total 'Вес насоса' or 'Вес "
            "агрегата'. For characteristics named 'Вес: Насоса', 'Вес: Электродвигателя', 'Вес: "
            "Общий вес агрегата', 'Вес: Фундаментной плиты', look for SEPARATE weight data (usually "
            "in detailed ТТХ/technical specs section). If the only weight info available is 'Масса, кг' "
            "in the dimensions table and the characteristic asks for total/aggregate weight, return "
            "null rather than taking catalog mass.\n"
            f"- If you cannot reliably identify the value for '{product_model}', return "
            "\"value\": null rather than guessing from another model.\n"
        )
    else:
        # Модель не задана — но все характеристики всё равно должны относиться к
        # ОДНОМУ изделию, а не быть собраны из разных моделей каталога.
        model_hint = (
            "\nIMPORTANT — SINGLE MODEL CONSISTENCY. The passport may list MANY pump models. "
            "No specific target model was given, so FIRST identify the single model whose "
            "characteristics best match the requested list, then extract ALL values from THAT "
            "ONE model only. Never combine values from different models/pages: it is a serious "
            "error to take Производительность from one model and Вес from another. Every "
            "characteristic must describe the SAME physical product. Prefer the model that has "
            "the most of the requested characteristics on the same page/table.\n"
        )

    count = len(target_names)
    return (
        "\n\n=== PASSPORT EXTRACTION SCOPE (overrides any earlier 'extract ALL' instruction) ===\n"
        f"Below is a fixed list of {count} characteristic NAMES. Your output MUST contain "
        f"EXACTLY these {count} characteristics — no more, no fewer — one object per name, "
        "in the SAME ORDER, using each name VERBATIM as the `name` field. "
        "Ignore every other characteristic in the passport; extract ONLY these.\n"
        "For each name, read its value AS WRITTEN IN THE PASSPORT for the requested model. "
        "You are NOT given the expected values — read them from the passport. "
        "Never invent, guess, or copy a value from the requirement: every value MUST come "
        "from the passport, and its quote_text/reference must contain that exact value. "
        "If a characteristic is genuinely absent from the passport, STILL include it with "
        "\"value\": null and an empty references array — do NOT drop it from the list.\n"
        "IMPORTANT for quote_text in references: always include enough context so the reader "
        "understands WHAT the value refers to. Write the characteristic label and value together, "
        "e.g. 'Напор, м 110', 'Мощность, кВт 30', 'L 1195', NOT just '110' or '30' or '1195'. "
        "Bare numbers are ambiguous and make it impossible to verify the match.\n"
        f"{model_hint}"
        f"The {count} characteristic names to return (verbatim, in order):\n{targets_json}"
    )


def build_s3_url(storage_key: str) -> str:
    endpoint = settings.S3_ENDPOINT.rstrip("/")
    bucket = settings.BUCKET_NAME.strip()
    return f"{endpoint}/{bucket}/{storage_key.lstrip('/')}"


def _refresh_presigned_url(storage_path: str) -> str | None:
    """Запрашивает свежий presigned URL у file-service по storage_path (ключу в S3)."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{settings.FILE_SERVICE_URL}/files/presign",
                params={"key": storage_path, "expires_in": 7200},
            )
            if resp.is_success:
                return resp.json().get("url")
    except Exception as exc:
        logger.warning("Failed to refresh presigned URL for %s: %s", storage_path, exc)
    return None


def run_extraction_task(
    analysis_id: str,
    file_id: str,
    file_type: str,
    storage_path: str,
    storage_url: str | None = None,
    extraction_backend: str | None = None,
    target_characteristics: list[dict] | None = None,
    product_model: str | None = None,
) -> dict:
    file_type = (file_type or "").lower()
    if not storage_path:
        raise ValueError(f"Missing storage_path for file {file_id}")

    # Всегда генерируем свежий presigned URL через file-service, чтобы избежать
    # истечения срока действия URL из БД (TTL 1 час)
    file_url = _refresh_presigned_url(storage_path)
    if not file_url:
        # Fallback: использовать сохранённый URL или прямой S3 URL
        if storage_url:
            file_url = storage_url
        elif settings.BUCKET_NAME:
            file_url = build_s3_url(storage_path)
        else:
            raise ValueError(f"Cannot build file URL for {file_id}: no presign, no storage_url, no BUCKET_NAME")

    with httpx.Client(timeout=settings.EXTRACTION_TIMEOUT_SECONDS) as client:
        prompt_resp = client.get(f"{settings.PROMPT_REGISTRY_URL}/prompts/{file_type}")
        _raise_for_status_with_detail(prompt_resp, "Prompt registry")
        prompt_payload = prompt_resp.json()

        extraction_payload = {
            "analysis_id": analysis_id,
            "file_id": file_id,
            "file_type": file_type,
            "file_url": file_url,
            "prompt": (
                (prompt_payload.get("prompt") or "")
                + _build_knowledge_base_prompt_appendix(file_type)
                + _build_product_model_appendix(file_type, product_model)
                + _build_target_characteristics_appendix(file_type, target_characteristics)
            ),
            "schema": prompt_payload.get("schema"),
            "backend": extraction_backend or settings.EXTRACTION_BACKEND,
        }

        extract_resp = client.post(
            f"{settings.EXTRACTION_SERVICE_URL}/extract",
            json=extraction_payload,
        )
        _raise_for_status_with_detail(extract_resp, "Extraction service")
        result_payload = extract_resp.json()
        # Порядок важен: сначала чиним плоский формат LLM-ответа во ВСЕХ местах
        # (result, pages[].extracted_data), и только потом собираем
        # extraction.products из pages — иначе он соберётся из искажённой структуры.
        if _normalize_flat_products_in_place(result_payload):
            logger.info(
                "Wrapped flat characteristics list into a product (analysis=%s file_type=%s)",
                analysis_id, file_type,
            )
        _normalize_docling_extraction(result_payload)

    debug_dir = Path(settings.EXTRACTION_DEBUG_DIR)
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_file_type = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in file_type
    ) or "unknown"
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    filename = f"{timestamp}_{analysis_id}_{file_id}_{safe_file_type}.json"
    target = debug_dir / filename
    with target.open("w", encoding="utf-8") as handle:
        json.dump(result_payload, handle, ensure_ascii=True, indent=2)

    return result_payload
