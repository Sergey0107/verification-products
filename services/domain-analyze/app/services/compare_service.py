import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

import httpx

from app.core.config import settings
from app.services.knowledge_base_client import list_canonical_attributes, search_knowledge

logger = logging.getLogger(__name__)


class CompareParseError(RuntimeError):
    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


def _extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _get_prompt() -> dict:
    with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.get(f"{settings.PROMPT_REGISTRY_URL}/prompts/comparison")
        resp.raise_for_status()
        return resp.json()


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _normalize_model(value: Any) -> str:
    """Нормализует код модели для устойчивого сравнения: нижний регистр,
    убираем пробелы и разделители (ГП-1500 / ГП 1500 / гп1500 → 'гп1500')."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s\-_.]+", "", value.strip().lower().replace("ё", "е"))


def _model_size_cores(value: Any) -> set[str]:
    """Числовое ядро типоразмера — самая стабильная часть кода между документами.
    Префикс (5Кс / КС / 1Кс) и исполнение (/4) различаются, ядро 'подача-напор'
    совпадает точно. 'КС 50-110/4' → {'50-110/4', '50-110'} ; '1Кс50-110' → {'50-110'}.
    Совпадение по ядру '50-110' надёжно связывает модель ТЗ с моделью паспорта."""
    if not isinstance(value, str):
        return set()
    norm = value.lower().replace("ё", "е").replace("–", "-").replace("—", "-").replace("х", "x")
    cores: set[str] = set()
    for match in re.findall(r"\d+(?:[-/x]\d+)+", norm):
        cores.add(match)
        base = match.split("/", 1)[0]
        if "-" in base:
            cores.add(base)
    return cores


def _models_match(tz_model: Any, passport_model: Any) -> bool:
    """Модели совпадают, если: (1) нормализованные строки равны/вложены, ИЛИ
    (2) есть общее числовое ядро типоразмера (устойчиво к разным префиксам).

    Сравнение больше НЕ отбрасывает изделия «не той» модели (все модели
    паспорта доходят до UI, он и фильтрует) — но сопоставление кода модели
    ТЗ с кодом модели паспорта по-прежнему нужно, чтобы пометить строки
    целевой модели, см. _mark_target_model_items."""
    norm_tz = _normalize_model(tz_model)
    norm_pp = _normalize_model(passport_model)
    if norm_tz and norm_pp and (norm_tz == norm_pp or norm_tz in norm_pp or norm_pp in norm_tz):
        return True
    tz_cores = _model_size_cores(tz_model)
    pp_cores = _model_size_cores(passport_model)
    return bool(tz_cores & pp_cores)


def _collect_products_from_pages(pages: Any) -> list[dict]:
    if not isinstance(pages, list):
        return []
    products: list[dict] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        extracted_data = page.get("extracted_data")
        if isinstance(extracted_data, dict):
            page_products = extracted_data.get("products")
            if isinstance(page_products, list):
                products.extend(
                    [item for item in page_products if isinstance(item, dict)]
                )
                continue
            if any(
                key in extracted_data
                for key in ("product_name", "product_model", "characteristics")
            ):
                products.append(extracted_data)
        elif isinstance(extracted_data, list):
            products.extend([item for item in extracted_data if isinstance(item, dict)])
    return products


def _normalize_products(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    # Источник products выбираем по приоритету. result.products — это полный,
    # необработанный ответ LLM (правильная вложенная структура изделий с
    # характеристиками). extraction.products собирается отдельно из pages и может
    # быть искажён (напр. flat-формат LLM разворачивается в N «изделий» с пустыми
    # characteristics) — поэтому берём его лишь как запасной вариант.
    candidates: list[dict] = []
    if isinstance(data.get("result"), dict):
        candidates.append(data["result"])
    if isinstance(data.get("extraction"), dict):
        candidates.append(data["extraction"])
    candidates.append(data)

    products: Any = None
    for source in candidates:
        if not isinstance(source, dict):
            continue
        candidate = source.get("products")
        if not isinstance(candidate, list):
            candidate = _collect_products_from_pages(source.get("pages"))
        # Берём первый источник, где есть продукт хотя бы с одной характеристикой —
        # иначе пустой/искажённый extraction.products «выиграл» бы у полного result.
        if isinstance(candidate, list) and any(
            isinstance(p, dict) and (p.get("characteristics") or [])
            for p in candidate
        ):
            products = candidate
            break
        if products is None and isinstance(candidate, list):
            products = candidate
    if not isinstance(products, list):
        return []
    normalized = []
    for product in products:
        if not isinstance(product, dict):
            continue
        name = _unwrap_value(product.get("product_name"))
        model = _unwrap_value(product.get("product_model"))
        characteristics = product.get("characteristics") or []
        norm_chars = []
        if isinstance(characteristics, list):
            for item in characteristics:
                if not isinstance(item, dict):
                    continue
                char_name = _unwrap_value(item.get("name"))
                char_value = _unwrap_value(item.get("value"))
                references = item.get("references") or []
                norm_chars.append(
                    {
                        "name": char_name,
                        "value": char_value,
                        "references": references if isinstance(references, list) else [],
                    }
                )
        normalized.append(
            {
                "product_name": name or "Неизвестное изделие",
                "product_model": model,
                "characteristics": norm_chars,
            }
        )
    return normalized


_GENERAL_PRODUCT_NAME = "Общее"


def _merge_general_into_products(products: list[dict]) -> list[dict]:
    """Домешивает характеристики продукта "Общее" (не привязанные к
    конкретному изделию) в КАЖДЫЙ остальной продукт, затем убирает "Общее"
    из списка. Раньше "Общее" участвовало в сравнении как отдельная
    псевдо-модель с собственным fallback-путём поиска пары в паспорте — то
    есть отдельный блок результата, которого по новой архитектуре быть не
    должно (сравниваются только два реальных изделия, "Общее" — не изделие).

    Специфичная для модели характеристика приоритетнее одноимённой из
    "Общее" — при конфликте имён общее значение не перезаписывает уже
    существующее в продукте (сравнение по нормализованной строке имени, без
    aliases: на этом этапе aliases ещё не построены — они зависят от
    итогового набора продуктов после мержа)."""
    general = next(
        (p for p in products if p.get("product_name") == _GENERAL_PRODUCT_NAME), None
    )
    if general is None:
        return products

    general_chars = general.get("characteristics") or []
    result: list[dict] = []
    for product in products:
        if product is general:
            continue
        existing_keys = {
            _normalize_char_name(c.get("name"))
            for c in (product.get("characteristics") or [])
            if isinstance(c, dict)
        }
        merged_chars = list(product.get("characteristics") or [])
        for char in general_chars:
            if not isinstance(char, dict):
                continue
            if _normalize_char_name(char.get("name")) in existing_keys:
                continue
            merged_chars.append(char)
        result.append({**product, "characteristics": merged_chars})
    return result


def _count_non_empty_characteristics(product: dict) -> int:
    return sum(
        1
        for c in (product.get("characteristics") or [])
        if isinstance(c, dict) and c.get("value")
    )


def _select_comparison_pair(
    tz_products: list[dict],
    passport_products: list[dict],
    tz_product_model: str | None,
    extraction_backend: str | None,
) -> tuple[dict | None, dict | None]:
    """Выбирает РОВНО одну пару (ТЗ-изделие, паспорт-изделие) для сравнения —
    никакой матрицы "каждое ТЗ-изделие против каждого паспорт-изделия".

    ТЗ трактуется как заказ на одно конкретное изделие: если продуктов ТЗ
    несколько, целевой определяется по приоритету:
    (a) tz_product_model (введённое пользователем в модалке загрузки),
        сматченный с product_model/product_name продуктов через _models_match;
    (b) product_model, уже извлечённый LLM внутри самого продукта ТЗ на
        этапе extraction (тот же источник, что читал старый continue_tz_review);
    (c) если неоднозначно — первый продукт (система всегда выбирает
        какое-то название, не оставляет изделие неопределённым).

    Пара в паспорте ищется по совпадению имени: точное product_name ->
    LLM-сопоставление по смыслу -> единственный fallback (самое наполненное
    изделие с каждой стороны, независимо друг от друга)."""
    if not tz_products or not passport_products:
        return None, None

    if len(tz_products) == 1:
        tz_product = tz_products[0]
    else:
        tz_product = None
        if tz_product_model:
            tz_product = next(
                (
                    p
                    for p in tz_products
                    if _models_match(tz_product_model, p.get("product_model"))
                    or _models_match(tz_product_model, p.get("product_name"))
                ),
                None,
            )
        if tz_product is None:
            tz_product = next(
                (p for p in tz_products if p.get("product_model")), None
            )
        if tz_product is None:
            tz_product = tz_products[0]

    target_name = tz_product.get("product_name")
    target_model = tz_product.get("product_model") or tz_product_model

    passport_product = next(
        (p for p in passport_products if p.get("product_name") == target_name), None
    )
    if passport_product is None and target_model:
        passport_product = next(
            (
                p
                for p in passport_products
                if _models_match(target_model, p.get("product_model"))
                or _models_match(target_model, p.get("product_name"))
            ),
            None,
        )
    if passport_product is None and len(passport_products) > 1:
        passport_product = _resolve_target_product_name(
            target_name, passport_products, extraction_backend
        )
    if passport_product is None:
        # Единственный fallback: самое наполненное изделие с каждой стороны,
        # независимо друг от друга.
        tz_product = max(tz_products, key=_count_non_empty_characteristics)
        passport_product = max(passport_products, key=_count_non_empty_characteristics)

    return tz_product, passport_product


def _resolve_target_product_name(
    tz_product_name: str | None,
    passport_products: list[dict],
    extraction_backend: str | None,
) -> dict | None:
    """Лёгкий LLM-запрос: "какое из этих названий изделий паспорта — то же
    самое, что это название из ТЗ" (по смыслу, а не по точному тексту).
    Отдельный небольшой промпт, а не весь документ — дёшево и быстро."""
    if not tz_product_name:
        return None
    passport_names = [
        p.get("product_name") for p in passport_products if p.get("product_name")
    ]
    if not passport_names:
        return None

    provider = _resolve_llm_provider(extraction_backend)
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    system_message = (
        "Тебе дано название изделия из технического задания и список названий "
        "изделий из паспорта продукции. Определи, какое из названий паспорта "
        "обозначает ТО ЖЕ САМОЕ физическое изделие, что и название из ТЗ (тип "
        "изделия при этом значения не имеет — сравнивай только совпадает ли "
        "конкретное наименование/обозначение модели). Если ни одно название "
        "паспорта не соответствует — верни null.\n\n"
        "Верни JSON: {\"passport_name\": \"...\"} или {\"passport_name\": null}."
    )
    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": json.dumps(
                    {"tz_product_name": tz_product_name, "passport_product_names": passport_names},
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            resp = client.post(
                f"{provider.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _extract_json(content)
    except Exception:
        logger.warning(
            "resolve_target_product_name: LLM call failed, falling back",
            exc_info=True,
            extra={"step": "compare_target_product_error"},
        )
        return None

    resolved_name = parsed.get("passport_name") if isinstance(parsed, dict) else None
    if not isinstance(resolved_name, str) or not resolved_name.strip():
        return None
    return next(
        (p for p in passport_products if p.get("product_name") == resolved_name), None
    )


# Слова, которые документы добавляют к названию характеристики, не меняя её
# смысла: ТЗ пишет «Напряжение», паспорт — «Напряжение электропитания»; ТЗ
# «Подача при напоре 10 м», паспорт — «Подача (расход) при напоре 10 м».
# Сопоставление по точному имени объявляло такие пары разными
# характеристиками, и обе половины уходили в «не найдено».
# Намеренно НЕ включает «максимальный/минимальный/номинальный»: это не шум, а
# разные величины («Максимальный напор» и «Номинальный напор» — разные строки
# паспорта), и их слияние дало бы ложные совпадения.
_CHAR_NAME_NOISE_RE = re.compile(
    r"\b(?:электропитани\w*|питани\w*|сети|не\s+менее|не\s+более)\b",
    re.IGNORECASE,
)
# Уточнение в скобках убирается вместе со скобками, но остальная часть имени
# сохраняется: «Подача (расход) при напоре 10 м» → «подача при напоре 10 м», а
# не «подача» — рабочая точка отличает характеристику от соседних.
_CHAR_NAME_PARENS_RE = re.compile(r"\([^)]*\)")
# Хвост после запятой — обычно единицы измерения: «Расход воды, л/с» = «Расход
# воды».
_CHAR_NAME_UNIT_RE = re.compile(r",.*$")


def _normalize_char_name(name: Any) -> str:
    """Ключ сопоставления характеристик ТЗ и паспорта.

    Приводит к сравнимому виду формулировки, различающиеся только уточняющими
    словами, единицами измерения и пунктуацией. Числа сохраняются: «при напоре
    10 м» и «при напоре 15 м» — разные рабочие точки, а не одна характеристика.
    """
    text = str(name or "").strip().lower().replace("ё", "е")
    if not text:
        return ""
    text = _CHAR_NAME_PARENS_RE.sub(" ", text)
    text = _CHAR_NAME_UNIT_RE.sub(" ", text)
    text = _CHAR_NAME_NOISE_RE.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Если убрали вообще всё (название состояло из одних уточнений) — держимся
    # исходного текста, иначе разные характеристики схлопнулись бы в одну.
    if not text:
        return re.sub(r"\s+", " ", str(name or "").strip().lower())
    return text


def _char_name_key(name: Any, aliases: dict[str, list[str]] | None) -> str:
    """Основной (первый) ключ сопоставления — используется там, где нужен
    ровно один ключ на имя (порядок строк сравнения, group-by в UI). Для
    поиска ВСЕХ кандидатов см. _char_name_keys ниже: одно имя паспорта может
    относиться сразу к нескольким ТЗ-требованиям (диапазон "от X до Y" в
    паспорте отвечает и на "минимальное значение", и на "максимальное" в
    ТЗ), и это не то же самое, что "не уверен, к чему из двух отнести"."""
    return _char_name_keys(name, aliases)[0]


def _char_name_keys(name: Any, aliases: dict[str, list[str]] | None) -> list[str]:
    """Все ключи сопоставления для имени: сперва пробуем семантические алиасы
    (см. _resolve_char_name_aliases), иначе — строковая нормализация как
    единственный ключ. Алиасы покрывают только то, что реально встретилось в
    документах и что LLM смогла сгруппировать; всё остальное продолжает
    работать как раньше.

    Список, а не одно значение: наивный dict[str, str] не может выразить
    «паспортное имя относится сразу к двум разным ТЗ-требованиям» — второе
    совпадение просто перезаписывало бы первое. С list[str] запись паспорта
    дублируется под каждым canonical_key, к которому она была отнесена (см.
    _build_char_map/_build_candidates_map)."""
    normalized = _normalize_char_name(name)
    if aliases:
        aliased = aliases.get(normalized)
        if aliased:
            return list(aliased)
    return [normalized]


def _build_char_map(
    products: list[dict], aliases: dict[str, list[str]] | None = None
) -> dict[str, dict[str, list[dict]]]:
    """Характеристика -> СПИСОК всех встреченных записей {value, references}, а не
    одна (последняя). Документ может упоминать одну характеристику несколько раз
    с разными (в т.ч. противоречивыми) значениями — например разные рабочие точки
    или опечатка в другой таблице; раньше более раннее упоминание молча
    перезаписывалось. Первый элемент списка остаётся "основным" для мест кода,
    которые пока умеют работать только с одним значением (LLM comparison prompt).

    Ключ — нормализованное имя (_normalize_char_name), при наличии aliases —
    семантический канонический ключ поверх него (см. _char_name_keys): ТЗ и
    паспорт называют одну характеристику по-разному, и точное совпадение
    находило пару лишь в единичных случаях. Если имени соответствует
    НЕСКОЛЬКО ключей (паспортный диапазон отвечает и на "минимальное", и на
    "максимальное" ТЗ-требование), запись дублируется под каждым — иначе
    она была бы видна только одной из двух ТЗ-строк. Исходное написание
    сохраняется в поле "name", чтобы в UI и промпте характеристика
    называлась так же, как в документе."""
    result: dict[str, dict[str, list[dict]]] = {}
    for product in products:
        product_name = product.get("product_name") or "Неизвестное изделие"
        result.setdefault(product_name, {})
        for item in product.get("characteristics", []):
            name = item.get("name")
            if not name:
                continue
            entry = {
                "name": name,
                "value": item.get("value"),
                "references": item.get("references", []),
            }
            for key in _char_name_keys(name, aliases):
                result[product_name].setdefault(key, []).append(entry)
    return result


def _ordered_characteristics(
    tz_chars: list[dict],
    passport_chars: list[dict],
    aliases: dict[str, list[str]] | None = None,
) -> list[tuple[str, str]]:
    """Пары (ключ сопоставления, отображаемое имя) в порядке ТЗ, затем паспорта.

    Ключ нормализован (и при наличии aliases — семантически сгруппирован),
    поэтому «Подача при напоре 10 м» из ТЗ и «Подача (расход) при напоре 10 м»
    из паспорта дают одну строку сравнения. Показываем название так, как оно
    записано в ТЗ (там формулировка требования), а для
    характеристик, которых в ТЗ нет, — как в паспорте.

    Один ключ на строку (первый из _char_name_keys, если их несколько) —
    строк сравнения по-прежнему ровно столько же, сколько уникальных имён;
    "многие ключи" используются только чтобы найти этой строке ВСЕ
    подходящие записи паспорта (см. _build_char_map/_build_candidates_map),
    а не чтобы размножить саму строку."""
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in list(tz_chars) + list(passport_chars):
        name = item.get("name")
        if not name:
            continue
        key = _char_name_key(name, aliases)
        if key in seen:
            continue
        ordered.append((key, name))
        seen.add(key)
    return ordered


def _extract_page_number(text: str | None) -> int | None:
    if not text:
        return None
    patterns = (
        r"(?:стр\.?|страниц[аеы]?|с\.?|page|p\.)\s*(\d{1,4})",
        r"(\d{1,4})\s*(?:стр\.?|страниц[аеы]?|page)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                page = int(match.group(1))
            except (TypeError, ValueError):
                return None
            return page if page > 0 else None
    return None


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _infer_bbox(bbox: Any) -> dict[str, float] | None:
    if not isinstance(bbox, dict) or not bbox:
        return None

    result: dict[str, float] = {}

    # Пробуем извлечь абсолютные координаты
    if all(key in bbox for key in ("x", "y", "width", "height")):
        try:
            result = {
                "x": float(bbox["x"]),
                "y": float(bbox["y"]),
                "width": float(bbox["width"]),
                "height": float(bbox["height"]),
            }
        except (TypeError, ValueError):
            return None
    elif all(key in bbox for key in ("x0", "y0", "x1", "y1")):
        try:
            x0 = float(bbox["x0"])
            y0 = float(bbox["y0"])
            x1 = float(bbox["x1"])
            y1 = float(bbox["y1"])
        except (TypeError, ValueError):
            return None
        result = {"x": x0, "y": y0, "width": max(0.0, x1 - x0), "height": max(0.0, y1 - y0)}
    elif all(key in bbox for key in ("left", "top", "right", "bottom")):
        try:
            left = float(bbox["left"])
            top = float(bbox["top"])
            right = float(bbox["right"])
            bottom = float(bbox["bottom"])
        except (TypeError, ValueError):
            return None
        result = {
            "x": left,
            "y": top,
            "width": max(0.0, right - left),
            "height": max(0.0, bottom - top),
        }
    else:
        return None

    # Сохраняем нормализованные координаты (norm_x0/norm_y0/norm_x1/norm_y1),
    # если они есть в исходном bbox — фронтенд использует их для точного позиционирования
    for norm_key in ("norm_x0", "norm_y0", "norm_x1", "norm_y1"):
        if norm_key in bbox:
            try:
                result[norm_key] = float(bbox[norm_key])
            except (TypeError, ValueError):
                pass

    return result


def _derive_matched_terms(*parts: Any) -> list[str]:
    tokens: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        tokens.extend(re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9./-]{1,}", part))
    return _dedupe_strings(tokens[:8])


def _matched_text_consistent_with_quote(
    matched_text: str | None, quote_text: str | None
) -> bool:
    """True, если matched_text согласуется с quote_text (один — подстрока другого).

    Фронтенд прячет спаны, где matched_text != quote_text (считает их «обманчивым
    якорём»). В таблицах геометрия находит строку по названию характеристики, а
    quote_text — это значение, поэтому такие корректные привязки терялись и в
    паспорте отображалась лишь одна характеристика. Тут — защита на стороне
    сравнения: если несогласованно, matched_text не пробрасываем."""
    if not matched_text or not quote_text:
        return False
    norm_m = re.sub(r"\s+", " ", str(matched_text).strip()).lower().replace("ё", "е")
    norm_q = re.sub(r"\s+", " ", str(quote_text).strip()).lower().replace("ё", "е")
    if not norm_m or not norm_q:
        return False
    return norm_m == norm_q or norm_q in norm_m or norm_m in norm_q


def _build_span_payload(
    *,
    fragment_type: str,
    locator_strategy: str,
    page_number: int | None,
    anchor_text: str | None,
    quote_text: str | None,
    locator_text: str | None,
    bbox: dict[str, float] | None,
    confidence: float | None,
    matched_text: str | None = None,
) -> dict[str, Any]:
    return {
        "fragment_type": fragment_type,
        "locator_strategy": locator_strategy,
        "page_number": page_number,
        "page": page_number,
        "anchor_text": anchor_text,
        "quote_text": quote_text,
        "locator_text": locator_text,
        "bbox": bbox,
        "confidence": confidence,
        "matched_text": matched_text,
    }


def _normalize_reference_span(reference: Any, fallback_quote: str | None) -> dict[str, Any] | None:
    if isinstance(reference, dict):
        unverified = reference.get("position_unverified") is True
        bbox = _infer_bbox(reference.get("bbox")) if not unverified else None
        page = reference.get("page")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        if not isinstance(page, int) or page <= 0:
            page = _extract_page_number(str(reference.get("locator_text") or reference.get("anchor_text") or ""))
        if unverified:
            page = None
        anchor_text = reference.get("anchor_text") or reference.get("text") or reference.get("locator_text")
        quote_text = reference.get("quote_text") or fallback_quote
        locator_text = reference.get("locator_text") or anchor_text or quote_text
        locator_strategy = reference.get("locator_strategy")
        if bbox:
            locator_strategy = locator_strategy or "bbox"
            fragment_type = "exact_span"
            confidence = reference.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.92
        elif page:
            locator_strategy = locator_strategy or "page_anchor"
            fragment_type = "page_anchor"
            confidence = reference.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.72
        else:
            locator_strategy = locator_strategy or "text_anchor"
            fragment_type = "text_anchor"
            confidence = reference.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.58
        raw_matched = reference.get("matched_text")
        matched_text = (
            raw_matched
            if _matched_text_consistent_with_quote(raw_matched, quote_text)
            else None
        )
        return _build_span_payload(
            fragment_type=fragment_type,
            locator_strategy=str(locator_strategy),
            page_number=page,
            anchor_text=anchor_text,
            quote_text=quote_text,
            locator_text=locator_text,
            bbox=bbox,
            confidence=float(confidence),
            matched_text=matched_text,
        )

    if isinstance(reference, str):
        anchor_text = reference.strip()
        if not anchor_text:
            return None
        page_number = _extract_page_number(anchor_text)
        return _build_span_payload(
            fragment_type="page_anchor" if page_number else "text_anchor",
            locator_strategy="page_anchor" if page_number else "text_anchor",
            page_number=page_number,
            anchor_text=anchor_text,
            quote_text=fallback_quote,
            locator_text=anchor_text,
            bbox=None,
            confidence=0.55 if page_number else 0.46,
        )

    return None


def _dedupe_source_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for span in spans:
        key = (
            span.get("fragment_type"),
            span.get("page_number"),
            span.get("anchor_text"),
            span.get("quote_text"),
            json.dumps(span.get("bbox"), ensure_ascii=False, sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return unique


def _clean_display_quote(
    quote: str | None, value: Any, characteristic_name: str | None
) -> str | None:
    """Формирует короткую читаемую подпись для колонки «Найдено в документации».

    LLM теперь получает таблицы как Markdown, поэтому quote_text характеристики из
    таблицы — это ЦЕЛАЯ строка вида 'модель | v1 | v2 | ... | vN'. Показывать её
    пользователю целиком бессмысленно (видно весь ряд таблицы вместо значения).
    Для Markdown-строк показываем «<характеристика> <значение>», а не сырой ряд."""
    if quote and "|" in quote and quote.count("|") >= 2:
        # Табличная Markdown-строка — заменяем на значение характеристики.
        val = str(value).strip() if value is not None else ""
        if val and characteristic_name:
            return f"{characteristic_name}: {val}"
        if val:
            return val
        # Фолбэк: первая непустая ячейка-значение (не код модели).
        cells = [c.strip() for c in quote.split("|") if c.strip()]
        cells = [c for c in cells if not re.fullmatch(r"[-:\s]+", c)]
        if len(cells) >= 2:
            return cells[1]
    if not quote:
        raw = str(value).strip() if value is not None else None
        if raw and characteristic_name:
            return f"{characteristic_name} {raw}"
        return raw
    return quote


def _build_evidence_payload(
    *,
    document_type: str,
    references: list[Any],
    quote: str | None,
    value: Any,
    characteristic_name: str | None = None,
) -> dict[str, Any]:
    source_spans: list[dict[str, Any]] = []
    for reference in references:
        span = _normalize_reference_span(reference, quote)
        if span is not None:
            source_spans.append(span)
    if not source_spans and quote:
        source_spans.append(
            _build_span_payload(
                fragment_type="fallback_quote",
                locator_strategy="fallback_quote",
                page_number=_extract_page_number(quote),
                anchor_text=quote,
                quote_text=quote,
                locator_text=quote,
                bbox=None,
                confidence=0.35,
            )
        )

    source_spans = _dedupe_source_spans(source_spans)
    page_anchors = [
        {
            "page_number": span["page_number"],
            "page": span["page_number"],
            "label": f"Страница {span['page_number']}",
        }
        for span in source_spans
        if isinstance(span.get("page_number"), int)
    ]
    page_anchors = list(
        {
            (anchor["page"], anchor["label"]): anchor
            for anchor in page_anchors
        }.values()
    )
    navigation_target = source_spans[0] if source_spans else None
    exact_span = next((span for span in source_spans if span.get("fragment_type") == "exact_span"), None)
    text_anchor = next(
        (
            span
            for span in source_spans
            if span.get("fragment_type") in {"text_anchor", "page_anchor", "fallback_quote"}
        ),
        None,
    )
    page_anchor = next((span for span in source_spans if span.get("page_number")), None)
    # display_quote — короткая подпись для UI. Markdown-строки таблиц превращаем в
    # «<характеристика>: <значение>», а не показываем весь ряд таблицы.
    fallback_quote = _clean_display_quote(quote, value, characteristic_name)
    locator_strategy = (
        exact_span.get("locator_strategy")
        if exact_span
        else page_anchor.get("locator_strategy")
        if page_anchor
        else text_anchor.get("locator_strategy")
        if text_anchor
        else "missing"
    )
    position_status = (
        "exact"
        if exact_span
        else "page_anchor"
        if page_anchor
        else "text_anchor"
        if text_anchor
        else "missing"
    )
    active_span = exact_span or page_anchor or text_anchor
    return {
        "evidence_version": "v2",
        "document_type": document_type,
        "position_status": position_status,
        "locator_strategy": locator_strategy,
        "display_quote": fallback_quote,
        "full_quote": fallback_quote,
        "fallback_quote": fallback_quote,
        "quote_origin": "model_quote" if quote else "reference_anchor" if source_spans else "missing",
        "matched_terms": _derive_matched_terms(fallback_quote, str(value) if value is not None else None),
        "confidence": max(
            (float(span.get("confidence")) for span in source_spans if isinstance(span.get("confidence"), (int, float))),
            default=0.0,
        ),
        "source_spans": source_spans,
        "page_anchors": page_anchors,
        "active_span": active_span,
        "exact_span": exact_span,
        "text_anchor": text_anchor,
        "page_anchor": page_anchor,
        "navigation_target": active_span or navigation_target,
    }


def _build_candidates_map(
    chars: list[dict], aliases: dict[str, list[str]] | None = None
) -> dict[str, list[dict]]:
    """Группирует характеристики по нормализованному (при наличии aliases —
    семантическому) имени в СПИСОК всех встреченных записей (не одну
    последнюю) — см. docstring _build_char_map. Имя с несколькими ключами
    дублируется под каждым (см. _char_name_keys)."""
    result: dict[str, list[dict]] = {}
    for c in chars:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        for key in _char_name_keys(name, aliases):
            result.setdefault(key, []).append(c)
    return result


def _primary_entry(candidates: list[dict]) -> dict:
    return candidates[0] if candidates else {}


def _compare_product_pair(
    tz_product: dict,
    passport_product: dict,
    aliases: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Сравнивает ОДНО изделие ТЗ с ОДНИМ изделием паспорта, объединяя
    характеристики по имени. Используется, когда с каждой стороны ровно одно
    изделие — тогда название изделия не важно (в паспорте оно часто пустое),
    и сравнивать надо напрямую, иначе характеристики задваиваются."""
    product_name = (
        tz_product.get("product_name")
        or passport_product.get("product_name")
        or "Неизвестное изделие"
    )
    tz_chars = tz_product.get("characteristics", []) or []
    passport_chars = passport_product.get("characteristics", []) or []
    tz_map = _build_candidates_map(tz_chars, aliases)
    passport_map = _build_candidates_map(passport_chars, aliases)
    items: list[dict] = []
    for char_key, char_name in _ordered_characteristics(tz_chars, passport_chars, aliases):
        tz_entry = _primary_entry(tz_map.get(char_key, []))
        passport_candidates = passport_map.get(char_key, [])
        passport_entry = _primary_entry(passport_candidates)
        items.append(
            {
                "product_name": product_name,
                "tz_product_name": tz_product.get("product_name") or product_name,
                "characteristic": char_name,
                "tz_value": tz_entry.get("value"),
                "passport_value": passport_entry.get("value"),
                "tz_references": tz_entry.get("references", []),
                "passport_references": passport_entry.get("references", []),
                "passport_value_candidates": passport_candidates,
            }
        )
    return items


def _mark_target_model_items(items: list[dict]) -> list[dict]:
    """Проставляет is_target_model=True у каждой строки сравнения.

    Раньше сравнение возвращало строки по ВСЕМ моделям паспорта сразу, и
    is_target_model отличал строку запрошенной пользователем модели от строк
    остальных моделей каталога (UI по умолчанию показывал только целевую).
    Теперь сравниваются ровно два уже выбранных изделия (см.
    _select_comparison_pair) — различать модели внутри результата больше не
    нужно, поле остаётся только для обратной совместимости контракта с
    api-gateway/фронтендом."""
    for item in items:
        item["is_target_model"] = True
    return items


def _build_kb_synonyms_appendix() -> str:
    """Готовые синонимы из Knowledge Base (canonical_attributes.synonyms) как
    подсказка для _resolve_char_name_aliases — те же данные, что уже
    используются в _build_kb_prompt_appendix для сравнения, но здесь
    подмешиваются РАНЬШЕ, на этапе группировки имён, а не после построения
    пар. Список короткий (десятки записей), поэтому передаём целиком, без
    привязки к конкретным items текущего анализа."""
    try:
        attributes = list_canonical_attributes()
    except Exception:
        logger.warning(
            "build_kb_synonyms_appendix: failed to fetch canonical attributes",
            exc_info=True,
        )
        return ""
    if not attributes:
        return ""
    lines = [
        "\n\nИзвестные канонические характеристики и их синонимы (используй как "
        "дополнительную подсказку, но не ограничивайся только ими):"
    ]
    for item in attributes[:200]:
        synonyms = ", ".join(str(v) for v in (item.get("synonyms") or [])[:8])
        name = item.get("name")
        if not name:
            continue
        line = f"- {name}"
        if synonyms:
            line += f" (синонимы: {synonyms})"
        lines.append(line)
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


_CHAR_ALIAS_SYSTEM_PROMPT = """Ты помогаешь сопоставить названия технических характеристик
из технического задания (ТЗ) и из паспорта/руководства по эксплуатации одного и того же
изделия. Разные документы часто называют одну и ту же физическую величину разными словами
(например «Вязкость перекачиваемой жидкости» и «Кинематическая вязкость перекачиваемого
масла» — одно и то же; «Напряжение питания» и «Напряжение электропитания сети» — одно и то
же; «Производительность» и «Подача» для насоса — одно и то же).

Тебе дан список названий характеристик ИЗ ТЗ (требования к изделию) и отдельно список названий
характеристик ИЗ ПАСПОРТА этой же конкретной модели изделия. Для КАЖДОГО названия из ТЗ найди
ВСЕ названия из паспорта, обозначающие ТУ ЖЕ физическую величину (может быть 0, 1 или несколько —
например если паспорт даёт минимальное/максимальное значение отдельными строками, а в ТЗ они
объединены одним требованием на диапазон, или наоборот). Разные величины (даже близкие —
например «Максимальный напор» и «Номинальный напор», разные рабочие точки вроде «напор 10 м» и
«напор 15 м») в один match не объединяй.

ОБРАТНЫЙ случай отдельно: если ПАСПОРТ даёт величину ОДНОЙ строкой-диапазоном («Рабочая
температура: от +1 до +25°C»), а ТЗ требует её же ДВУМЯ отдельными строками («Минимальная
температура: +1°C» и «Максимальная температура: +25°C») — верни ЭТО ЖЕ паспортное название в
passport_names для ОБОИХ tz_name («Минимальная...» и «Максимальная...»), не только для одного
из них. Одно название паспорта не «занято» — оно может законно входить в match нескольких
разных названий ТЗ одновременно, если каждое из них — часть того же диапазона/факта.

ВАЖНО про короткие/общие названия: один документ часто называет характеристику общим словом
(«Мощность», «Напор», «Расход», «Напряжение»), а другой — тем же словом с уточняющим
существительным без изменения смысла величины («Мощность двигателя», «Напор насоса», «Расход
жидкости», «Напряжение питания», «Напряжение электродвигателя», «Напряжение сети») — это ОДНА
И ТА ЖЕ характеристика, группируй их вместе. Особенно для ЭЛЕКТРИЧЕСКИХ параметров питания
(напряжение, ток, частота, число фаз) — у изделия почти всегда ОДНА точка подключения к
электросети, поэтому «Напряжение питания», «Напряжение сети», «Напряжение электродвигателя» и
просто «Напряжение» почти наверняка одна и та же величина (сетевое напряжение, на которое
рассчитан весь агрегат/электродвигатель), даже если формулировки называют разные узлы —
разделяй их только при явном признаке нескольких НЕЗАВИСИМЫХ источников питания в одном
изделии (например отдельно управляющая электроника на 24В и силовой двигатель на 380В).

Отличай такое уточнение (не меняет физическую величину) от модификатора, который меняет её
(максимальный/минимальный/номинальный/расчётный, разные рабочие точки, или разные МЕХАНИЧЕСКИЕ
узлы с независимой мощностью/производительностью — «мощность двигателя» вс. «мощность насоса»
у агрегата, где двигатель и насос имеют разный КПД и разную мощность на валу, поэтому это
разные числа, не просто разные слова для одного) — такие модификаторы обозначают разные
величины и группировать их нельзя.

Не объединяй характеристики, если не уверен, что это одна и та же величина — ложное
объединение хуже, чем пропущенное совпадение. Но не будь излишне осторожен с очевидными
случаями выше (короткое общее имя vs то же имя с уточнением, не меняющим величину) — это
самый частый и самый безопасный тип совпадения, и его пропуск — типичная ошибка.

Верни JSON: {"matches": [{"tz_name": "...", "passport_names": ["...", "..."]}, ...]}.
Ровно один объект на каждое входное название из ТЗ (в том же порядке, что дан список ТЗ).
passport_names — список найденных названий из паспорта (пустой список [], если совпадений
нет — не пропускай ТЗ-название целиком)."""

# Fallback-версия промпта для _resolve_char_name_aliases_whole_document: та
# же логика группировки синонимов, но без разделения на "список ТЗ" и
# "список паспорта" — используется только для ТЗ-продуктов, для которых
# _models_match не нашла паспорт-модель (per-model explicit matching
# неприменим, см. docstring _resolve_char_name_aliases).
_CHAR_ALIAS_WHOLE_DOC_SYSTEM_PROMPT = """Ты помогаешь сопоставить названия технических
характеристик из технического задания (ТЗ) и из паспорта/руководства по эксплуатации одного и
того же изделия. Разные документы часто называют одну и ту же физическую величину разными
словами (например «Вязкость перекачиваемой жидкости» и «Кинематическая вязкость перекачиваемого
масла» — одно и то же; «Мощность» и «Мощность двигателя» — одно и то же).

Тебе дан список названий характеристик (каждое — отдельная строка из ТЗ или паспорта, могут
повторяться). Сгруппируй их по физическому смыслу: названия, обозначающие ОДНУ И ТУ ЖЕ
величину, получают один и тот же canonical_key (короткая нормализованная строка на русском
языке, нижний регистр, без единиц измерения). Названия, обозначающие РАЗНЫЕ величины (даже
близкие — например «Максимальный напор» и «Номинальный напор», или значения при разных рабочих
точках вроде «напор 10 м» и «напор 15 м»), НЕ группируй вместе — оставляй им разные
canonical_key. Не объединяй характеристики, если не уверен, что это одна и та же величина.

Верни JSON: {"groups": [{"canonical_key": "...", "names": ["...", "..."]}, ...]}.
Каждое входное название должно попасть ровно в одну группу. Названия, для которых нет
явного синонима, всё равно образуют собственную группу из одного имени."""

# Размер чанка для группировки имён характеристик (см. _resolve_char_name_aliases).
# Меньше, чем COMPARE_CHUNK_SIZE (для самого сравнения) — там LLM оценивает
# готовые пары значений, здесь ей нужно удерживать в внимании весь список
# сразу, чтобы заметить совпадения между удалёнными друг от друга именами;
# с большими списками (300+) она почти перестаёт группировать вообще (см.
# docstring ниже).
_CHAR_ALIAS_CHUNK_SIZE = 40


def _resolve_char_name_aliases(
    tz_products: list[dict],
    passport_products: list[dict],
    extraction_backend: str | None = None,
) -> dict[str, list[str]]:
    """Семантическая группировка названий характеристик ТЗ/паспорта в один
    canonical_key через LLM — до построения _build_char_map. Строковая
    нормализация (_normalize_char_name) не понимает синонимы («Вязкость
    перекачиваемой жидкости» и «Кинематическая вязкость перекачиваемого
    масла» физически одно и то же, но как строки не совпадают), из-за чего
    такие пары никогда не попадали в сравнение, даже когда значения есть в
    обоих документах.

    Раньше это был ОДИН LLM-запрос на весь документ (даже разбитый на
    чанки по алфавиту) — и модель группировала почти никак: реальные случаи
    на документах — "Мощность"/"Мощность двигателя", "Нормальный напор"/
    "Напор насоса" не находили пару, хотя явно одна и та же величина (см.
    обсуждение с пользователем). Проблема — абстрактная группировка списка
    из сотен несвязанных строк без контекста, какая с какой стороны
    документа; здесь вместо этого делаем per-model EXPLICIT MATCHING: для
    каждой пары (ТЗ-модель, её паспорт-модели по _models_match) — отдельный
    запрос с ДВУМЯ явными списками (что в ТЗ / что в паспорте ЭТОЙ модели) и
    прямой задачей "для каждого имени из ТЗ найди все подходящие из
    паспорта" — контекст на порядок компактнее и точнее, к тому же
    естественно поддерживает 1-ко-многим (см. _CHAR_ALIAS_SYSTEM_PROMPT):
    если паспорт даёт "Минимальная/Максимальная температура" отдельными
    строками на одно ТЗ-требование "Рабочая температура" — оба попадут в
    один canonical_key, и уже существующий passport_value_candidates покажет
    их вложенным списком, ничего доп. переделывать не нужно.

    Возвращает {normalized_name: [canonical_key, ...]} — обычно один
    элемент, используется в _char_name_keys/_build_char_map. Список, а не
    одно значение: паспортное имя может законно относиться сразу к
    НЕСКОЛЬКИМ ТЗ-требованиям (диапазон "от X до Y" отвечает и на
    "минимальное", и на "максимальное") — простой dict[str, str] потерял
    бы второе совпадение при перезаписи первого."""
    aliases: dict[str, list[str]] = {}

    # Пары "ТЗ-модель -> её паспорт-модели" через уже существующий
    # _models_match (числовое ядро типоразмера). Вызывающая сторона
    # (_build_comparison_items_with_aliases) сейчас всегда передаёт ровно
    # один продукт с каждой стороны — уже выбранную пару (см.
    # _select_comparison_pair) — но эта функция остаётся общей и на случай
    # вызова с несколькими продуктами не отбрасывает лишнее: идёт от каждой
    # ТЗ-модели ко ВСЕМ подходящим паспорт-моделям (не 1:1) — паспорт мог не
    # разложить характеристики по вариантам, тогда relevant-паспорт-имена
    # размазаны по нескольким продуктам с тем же числовым ядром.
    #
    # Если у ТЗ-продукта нет числового совпадения (напр. ТЗ называет изделие
    # обозначением заказчика "НП-1" без типоразмера, а паспорт — маркой
    # производителя "КМХ (В 6,45) 50-50..." — коды физически никак не
    # пересекаются, но это ОДНО И ТО ЖЕ изделие, просто у сторон разные
    # системы именования) и ТЗ-продуктов немного — берём тоже ВСЕ паспорт-
    # продукты кандидатами, а не молча падаем в слабый групповой fallback
    # ниже (реальный случай, где это сломало сопоставление: ТЗ="НП-1" без
    # product_model, паспорт из двух КМХ-моделей — model_pairs было бы
    # пустым, и даже точное "Мощность"/"Мощность двигателя" не находились).
    model_pairs: list[tuple[dict, list[dict]]] = []
    unmatched_tz_products: list[dict] = []
    for tz_product in tz_products:
        tz_model = tz_product.get("product_model") or tz_product.get("product_name")
        matched_passport = [
            pp
            for pp in passport_products
            if _models_match(tz_model, pp.get("product_model") or pp.get("product_name"))
        ]
        if not matched_passport and len(tz_products) <= 3 and passport_products:
            matched_passport = list(passport_products)
        if matched_passport:
            model_pairs.append((tz_product, matched_passport))
        else:
            unmatched_tz_products.append(tz_product)

    provider = _resolve_llm_provider(extraction_backend)
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    system_message = _CHAR_ALIAS_SYSTEM_PROMPT + _build_kb_synonyms_appendix()

    def _dedup_names(products: list[dict]) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for product in products:
            for item in product.get("characteristics", []):
                name = item.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                normalized = _normalize_char_name(name)
                if normalized in seen:
                    continue
                seen.add(normalized)
                names.append(name)
        return names

    def _resolve_pair(tz_product: dict, matched_passport: list[dict]) -> dict[str, list[str]]:
        tz_names = _dedup_names([tz_product])
        passport_names = _dedup_names(matched_passport)
        if not tz_names or not passport_names:
            return {}
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_message},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"tz_names": tz_names, "passport_names": passport_names},
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = _extract_json(content)
        except Exception:
            logger.warning(
                "resolve_char_name_aliases: LLM call failed for a model pair, skipping it",
                exc_info=True,
                extra={"step": "compare_char_aliases_error"},
            )
            return {}

        matches = parsed.get("matches") if isinstance(parsed, dict) else None
        if not isinstance(matches, list):
            logger.warning(
                "resolve_char_name_aliases: unexpected response shape for a model pair, ignoring",
                extra={"step": "compare_char_aliases_bad_shape"},
            )
            return {}

        # Многие-к-одному в обе стороны: одно паспортное имя (диапазон
        # "от X до Y") законно матчится сразу к нескольким tz_name ("мин" и
        # "макс" отдельными строками) — добавляем canonical_key в список
        # вместо перезаписи, иначе второе совпадение стирало бы первое.
        pair_aliases: dict[str, list[str]] = {}

        def _add_alias(name_key: str, canonical_key: str) -> None:
            keys = pair_aliases.setdefault(name_key, [])
            if canonical_key not in keys:
                keys.append(canonical_key)

        for match in matches:
            if not isinstance(match, dict):
                continue
            tz_name = match.get("tz_name")
            passport_matched = match.get("passport_names")
            if not isinstance(tz_name, str) or not tz_name.strip():
                continue
            if not isinstance(passport_matched, list) or not passport_matched:
                continue
            canonical_key = _normalize_char_name(tz_name)
            _add_alias(canonical_key, canonical_key)
            for passport_name in passport_matched:
                if not isinstance(passport_name, str) or not passport_name.strip():
                    continue
                _add_alias(_normalize_char_name(passport_name), canonical_key)
        return pair_aliases

    started_at = time.monotonic()
    if model_pairs:
        # Модели независимы — тот же паттерн параллелизации, что уже
        # используется для чанков самого сравнения (compare_json) — потоки,
        # т.к. каждый вызов — блокирующий HTTP-запрос.
        with ThreadPoolExecutor(max_workers=min(8, len(model_pairs))) as executor:
            for pair_aliases in executor.map(lambda pair: _resolve_pair(*pair), model_pairs):
                for name_key, canonical_keys in pair_aliases.items():
                    existing = aliases.setdefault(name_key, [])
                    for key in canonical_keys:
                        if key not in existing:
                            existing.append(key)

    if unmatched_tz_products:
        # Fallback на старый алгоритм (весь документ одним чанкованным
        # списком) — только для того, что per-model подход не покрыл. Свой
        # промпт (групповой формат, а не explicit tz/passport matching) —
        # каждое имя строго в одной группе, поэтому здесь всегда список из
        # одного элемента.
        whole_doc_system_message = (
            _CHAR_ALIAS_WHOLE_DOC_SYSTEM_PROMPT + _build_kb_synonyms_appendix()
        )
        whole_doc_aliases = _resolve_char_name_aliases_whole_document(
            unmatched_tz_products, passport_products, provider, headers, whole_doc_system_message
        )
        for name_key, canonical_key in whole_doc_aliases.items():
            aliases.setdefault(name_key, [canonical_key])

    _apply_prefix_fallback_aliases(aliases)

    logger.info(
        "resolve_char_name_aliases: %d model pair(s), %d unmatched TZ product(s), "
        "%d aliases resolved in %.2fs",
        len(model_pairs), len(unmatched_tz_products),
        len({key for keys in aliases.values() for key in keys}),
        time.monotonic() - started_at,
        extra={"step": "compare_char_aliases_response"},
    )
    return aliases


def _resolve_char_name_aliases_whole_document(
    tz_products: list[dict],
    passport_products: list[dict],
    provider: "_LlmProvider",
    headers: dict[str, str],
    system_message: str,
) -> dict[str, str]:
    """Fallback-путь для _resolve_char_name_aliases: та же группировка одним
    большим списком имён документа, что использовалась раньше — применяется
    только к ТЗ-продуктам, для которых не нашлось модели-пары в паспорте
    (_models_match), поэтому per-model explicit matching неприменим."""
    raw_names: list[str] = []
    seen_normalized: set[str] = set()
    for product in list(tz_products) + list(passport_products):
        for item in product.get("characteristics", []):
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            normalized = _normalize_char_name(name)
            if normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            raw_names.append(name)

    if len(raw_names) < 2:
        return {}

    sorted_names = sorted(raw_names, key=lambda n: _normalize_char_name(n))
    chunk_size = _CHAR_ALIAS_CHUNK_SIZE
    name_chunks = [
        sorted_names[i : i + chunk_size] for i in range(0, len(sorted_names), chunk_size)
    ]

    def _resolve_chunk(chunk: list[str]) -> dict[str, str]:
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": json.dumps({"names": chunk}, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = _extract_json(content)
        except Exception:
            logger.warning(
                "resolve_char_name_aliases_whole_document: LLM call failed for a chunk, skipping",
                exc_info=True,
                extra={"step": "compare_char_aliases_error"},
            )
            return {}

        groups = parsed.get("groups") if isinstance(parsed, dict) else None
        if not isinstance(groups, list):
            return {}
        chunk_aliases: dict[str, str] = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            canonical_key = group.get("canonical_key")
            names = group.get("names")
            if not isinstance(canonical_key, str) or not canonical_key.strip():
                continue
            if not isinstance(names, list):
                continue
            canonical_key = canonical_key.strip().lower()
            for name in names:
                if not isinstance(name, str) or not name.strip():
                    continue
                chunk_aliases[_normalize_char_name(name)] = canonical_key
        return chunk_aliases

    aliases: dict[str, str] = {}
    if len(name_chunks) == 1:
        aliases.update(_resolve_chunk(name_chunks[0]))
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(name_chunks))) as executor:
            for chunk_result in executor.map(_resolve_chunk, name_chunks):
                aliases.update(chunk_result)
    return aliases


def _apply_prefix_fallback_aliases(aliases: dict[str, list[str]]) -> None:
    """Детерминированная подстраховка поверх LLM-группировки: LLM иногда
    оставляет короткое общее имя («мощность») и то же имя с уточняющим
    существительным («мощность двигателя») в разных группах, хотя это одна
    и та же величина — самый частый и при этом самый безопасный тип
    совпадения (см. обсуждение с пользователем: реальный случай на
    документе с насосом, где такая пара НЕ сгруппировалась и потеряла
    совпадение). Правило узкое специально: объединяет normalized_key A и B,
    только если один — префикс другого ПО ГРАНИЦЕ СЛОВА (не буквенная
    подстрока — иначе "напор" слился бы с "наработка"), и это ЕДИНСТВЕННЫЙ
    такой кандидат для A среди всех ключей (если для "мощность" есть и
    "мощность двигателя", и "мощность насоса" — они формально разные узлы
    одного изделия, неоднозначность, объединять нельзя — оставляем решение
    LLM). Мутирует aliases на месте, дополняя (не заменяя) то, что вернула
    модель — не понижает уверенность LLM-группировки, только добивает
    случаи, которые она пропустила."""
    keys = set(aliases.keys())
    for key in list(keys):
        # Уже сгруппирован LLM с чем-то другим (или относится к нескольким
        # группам сразу) — доверяем её решению, не переопределяем.
        if aliases.get(key) != [key]:
            continue
        candidates = [
            other
            for other in keys
            if other != key and other.startswith(key + " ")
        ]
        if len(candidates) != 1:
            continue
        other = candidates[0]
        # Аналогично: не трогаем, если "other" уже осмысленно сгруппирован
        # LLM с чем-то третьим — тогда неясно, входит ли туда и наш "key".
        if aliases.get(other) != [other]:
            continue
        aliases[other] = [key]


def _build_comparison_items_with_aliases(
    tz_data: dict,
    passport_data: dict,
    extraction_backend: str | None = None,
    tz_product_model: str | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Выбирает пару изделий (см. _select_comparison_pair) и строит по ней
    строки сравнения, заодно отдавая наружу aliases (normalized_name ->
    canonical_key) — нужно api-gateway, чтобы
    характеристики ТЗ в document_characteristics (панель "как есть в
    документе") связывались с той же строкой сравнения, что и одноимённый
    (по смыслу) синоним где-то в документе (см. обсуждение с пользователем:
    ТЗ реально содержит и "Частота питающей сети", и "Частота сети" как
    отдельные вхождения — alias-резолвер верно группирует их одним ключом
    сравнения, но в саму строку сравнения попадает только ОДНО из двух
    имён; без aliases api-gateway не мог бы связать "непобедившее" имя с
    той же строкой, и статус в левой панели пропадал).

    Наружу отдаём ровно один canonical_key на имя (первый из
    _char_name_keys), даже если внутри сравнения имя участвует в
    нескольких группах (диапазон паспорта -> два ТЗ-требования, см.
    _build_char_map) — api-gateway использует этот ключ как единственный
    идентификатор связи "характеристика документа -> строка сравнения",
    и два ключа на одно и то же сырое имя документа сломали бы эту связь."""
    tz_products = _merge_general_into_products(_normalize_products(tz_data))
    passport_products = _merge_general_into_products(_normalize_products(passport_data))
    tz_product, passport_product = _select_comparison_pair(
        tz_products, passport_products, tz_product_model, extraction_backend
    )
    if tz_product is None or passport_product is None:
        return [], {}

    aliases = _resolve_char_name_aliases(
        [tz_product], [passport_product], extraction_backend
    )
    items = _mark_target_model_items(
        _compare_product_pair(tz_product, passport_product, aliases)
    )
    primary_aliases = {name: keys[0] for name, keys in aliases.items() if keys}
    return items, primary_aliases


def _attach_evidence_to_comparison(item: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    tz_quote = comparison.get("tz_quote")
    passport_quote = comparison.get("passport_quote")
    char_name = item.get("characteristic") or comparison.get("characteristic")
    comparison["tz_evidence"] = _build_evidence_payload(
        document_type="tz",
        references=item.get("tz_references", []),
        quote=tz_quote if isinstance(tz_quote, str) else None,
        value=item.get("tz_value"),
        characteristic_name=char_name,
    )
    comparison["passport_evidence"] = _build_evidence_payload(
        document_type="passport",
        references=item.get("passport_references", []),
        quote=passport_quote if isinstance(passport_quote, str) else None,
        value=item.get("passport_value"),
        characteristic_name=char_name,
    )
    # Документ может упоминать характеристику несколько раз с разными (в т.ч.
    # противоречивыми) значениями — passport_value/passport_evidence выше несут
    # только ПЕРВОЕ упоминание (для обратной совместимости с местами кода,
    # которые понимают одно значение). Здесь строим evidence на КАЖДОГО
    # кандидата, чтобы фронтенд мог показать и подсветить все варианты.
    passport_candidates = item.get("passport_value_candidates") or []
    candidates_payload: list[dict[str, Any]] = []
    for candidate in passport_candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_value = candidate.get("value")
        candidates_payload.append(
            {
                "value": candidate_value,
                "evidence": _build_evidence_payload(
                    document_type="passport",
                    references=candidate.get("references", []),
                    quote=None,
                    value=candidate_value,
                    characteristic_name=char_name,
                ),
            }
        )
    comparison["passport_value_candidates"] = candidates_payload
    return comparison


def _normalize_value_for_match(value: Any) -> str | None:
    """Нормализует значение для простого сравнения: обрезает пробелы, приводит к нижнему регистру."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _values_clearly_match(tz_value: Any, passport_value: Any) -> bool:
    """Возвращает True, если значения однозначно совпадают (точное совпадение после нормализации)."""
    norm_tz = _normalize_value_for_match(tz_value)
    norm_passport = _normalize_value_for_match(passport_value)
    if norm_tz is None or norm_passport is None:
        return False
    return norm_tz == norm_passport


_MISSING_VALUE_NOTE_RE = re.compile(
    r"(отсутствует|не найден|не указан|нет данных|нет в паспорте|нет в тз)",
    re.IGNORECASE,
)


def _note_contradicts_value(note: Any, passport_value: Any, tz_value: Any) -> bool:
    """LLM иногда пишет в note «характеристика отсутствует в паспорте/ТЗ», хотя сама же
    строка сравнения содержит непустое passport_value/tz_value (извлечённое из документа
    независимо от LLM). Такой note противоречит фактическим данным и вводит пользователя
    в заблуждение — характеристика на самом деле найдена, просто LLM ошиблась в пояснении."""
    if not isinstance(note, str) or not note.strip():
        return False
    if not _MISSING_VALUE_NOTE_RE.search(note):
        return False
    passport_present = bool(str(passport_value).strip()) if passport_value is not None else False
    tz_present = bool(str(tz_value).strip()) if tz_value is not None else False
    return passport_present and tz_present


def _chunk(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


class _LlmProvider(NamedTuple):
    name: str
    base_url: str
    api_key: str
    model: str


def _resolve_llm_provider(extraction_backend: str | None) -> _LlmProvider:
    """Сравнение всегда идёт через AI Tunnel — быстрее Yandex AI Studio на
    том же классе моделей (Yandex — таймауты в 20 минут, reasoning-режим
    qwen3 через Yandex занимал 200-600 сек на чанк даже при штатной работе,
    см. обсуждение с пользователем). Yandex остаётся только аварийным
    fallback'ом, если OPENROUTER_API_KEY не задан."""
    if settings.OPENROUTER_API_KEY:
        return _LlmProvider(
            name="ai_tunnel",
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            model=settings.AITUNNEL_COMPARE_MODEL or settings.OPENROUTER_MODEL,
        )
    logger.warning(
        "compare: OPENROUTER_API_KEY is not set, falling back to Yandex AI Studio",
        extra={"step": "compare_provider_fallback"},
    )
    return _LlmProvider(
        name="yandex_ai_studio",
        base_url=settings.YANDEX_BASE_URL,
        api_key=settings.YANDEX_API_KEY,
        # AI Studio требует полный идентификатор вида
        # gpt://<folder>/<model>, короткое имя не принимается.
        model=f"gpt://{settings.YANDEX_FOLDER_ID}/{settings.YANDEX_COMPARE_MODEL}",
    )


def _compare_chunk(items: list[dict], extraction_backend: str | None = None) -> dict:
    if not items:
        return {"comparisons": [], "summary": ""}
    prompt_payload = _get_prompt()
    prompt_text = prompt_payload.get("prompt", "")
    schema = prompt_payload.get("schema", {})
    kb_appendix = _build_kb_prompt_appendix(items)

    system_message = (
        f"{prompt_text}\n\nReturn JSON that matches this schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
        f"{kb_appendix}"
    )
    user_message = json.dumps(
        {"comparison_items": items},
        ensure_ascii=False,
    )

    provider = _resolve_llm_provider(extraction_backend)
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    started_at = time.monotonic()
    logger.info(
        "compare_chunk: sending %d items to %s (%s)",
        len(items), provider.model, provider.name,
        extra={"step": "compare_chunk_request"},
    )
    # До 3 попыток на временные сбои провайдера (5xx, обрыв соединения) —
    # единичный 503 от AI Tunnel/Yandex не должен валить весь анализ (см.
    # обсуждение с пользователем: реальный сбой на 503 Service Unavailable
    # уронил compare_documents целиком через ThreadPoolExecutor.map, хотя
    # повторный запрос почти наверняка прошёл бы). 4xx (неверный ключ,
    # некорректный payload) НЕ ретраятся — повтор с теми же данными даст тот
    # же результат, задержка только маскирует настоящую ошибку.
    max_attempts = 3
    retry_base_delay_seconds = 5.0
    data: dict | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == max_attempts:
                raise
            delay = retry_base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "compare_chunk: %s on attempt %d/%d, retrying in %.0fs",
                exc, attempt, max_attempts, delay,
                extra={"step": "compare_chunk_retry"},
            )
            time.sleep(delay)
        except httpx.TransportError as exc:
            if attempt == max_attempts:
                raise
            delay = retry_base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "compare_chunk: %s on attempt %d/%d, retrying in %.0fs",
                exc, attempt, max_attempts, delay,
                extra={"step": "compare_chunk_retry"},
            )
            time.sleep(delay)
    assert data is not None  # достигается только по break выше

    elapsed = time.monotonic() - started_at
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    logger.info(
        "compare_chunk: response received in %.2fs usage=%s content_len=%d",
        elapsed, data.get("usage"), len(content),
        extra={"step": "compare_chunk_response"},
    )
    try:
        return _extract_json(content)
    except json.JSONDecodeError as exc:
        logger.warning(
            "compare_chunk: failed to parse LLM response as JSON: %s", exc,
            extra={"step": "compare_chunk_parse_error"},
        )
        raise CompareParseError(str(exc), content)


def _build_kb_prompt_appendix(items: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    try:
        attributes = list_canonical_attributes()
    except Exception:
        logger.warning("Failed to fetch canonical attributes from knowledge-base", exc_info=True)
        attributes = []
    if attributes:
        lines = ["\nКанонические атрибуты из Knowledge Base:"]
        for item in attributes[:100]:
            synonyms = ", ".join(str(v) for v in (item.get("synonyms") or [])[:8])
            lines.append(
                f"- normalized_name={item.get('normalized_name')}; name={item.get('name')}; "
                f"unit={item.get('unit')}; value_type={item.get('value_type')}; synonyms={synonyms}"
            )
        sections.append("\n".join(lines))

    query_terms: list[str] = []
    for item in items[:20]:
        characteristic = item.get("characteristic")
        product_name = item.get("product_name")
        if isinstance(characteristic, str):
            query_terms.append(characteristic)
        if isinstance(product_name, str):
            query_terms.append(product_name)
    retrieval_query = " ; ".join(query_terms[:12])
    if retrieval_query:
        try:
            retrieval = search_knowledge(retrieval_query, limit=5)
        except Exception:
            logger.warning("Failed to search knowledge-base for %r", retrieval_query, exc_info=True)
            retrieval = []
        if retrieval:
            lines = ["\nРелевантные выдержки из Knowledge Base:"]
            for result in retrieval:
                lines.append(
                    f"- [{result.get('source_key')} v{result.get('source_version')}] "
                    f"{result.get('source_title')}: {result.get('text')}"
                )
            sections.append("\n".join(lines))

    if not sections:
        return ""
    return "\n\nИспользуй следующую Knowledge Base как источник истины для нормализации терминов и объяснимого сравнения:\n" + "\n\n".join(sections)


def _repair_json(raw_text: str, schema: dict, extraction_backend: str | None = None) -> dict:
    logger.info(
        "repair_json: attempting to repair unparsable LLM response (%d chars)", len(raw_text),
        extra={"step": "compare_repair_json"},
    )
    system_message = (
        "Ты — валидатор JSON. Преобразуй входной текст в валидный JSON, "
        "строго соответствующий схеме. Верни ТОЛЬКО JSON без пояснений."
    )
    user_message = json.dumps(
        {"schema": schema, "raw": raw_text},
        ensure_ascii=False,
    )
    provider = _resolve_llm_provider(extraction_backend)
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{provider.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return _extract_json(content)


def compare_json(
    tz_data: dict,
    passport_data: dict,
    extraction_backend: str | None = None,
    tz_product_model: str | None = None,
) -> dict:
    started_at = time.monotonic()
    items, char_name_aliases = _build_comparison_items_with_aliases(
        tz_data, passport_data, extraction_backend, tz_product_model
    )
    logger.info(
        "compare_json started: %d comparison items", len(items),
        extra={"step": "compare_json_start"},
    )
    if not items:
        logger.warning(
            "compare_json: no comparison items built from tz_data/passport_data",
            extra={"step": "compare_json_start"},
        )
        return {
            "match": False,
            "summary": "Нет данных для сравнения.",
            "comparisons": [],
            "char_name_aliases": char_name_aliases,
        }

    chunk_size = settings.COMPARE_CHUNK_SIZE
    chunks = _chunk(items, chunk_size)
    logger.info(
        "compare_json: split into %d chunk(s) of size<=%d", len(chunks), chunk_size,
        extra={"step": "compare_json_chunks"},
    )

    def _process_chunk(indexed: tuple[int, list[dict]]) -> tuple[list[dict], str | None]:
        chunk_index, chunk_items = indexed
        try:
            result = _compare_chunk(chunk_items, extraction_backend)
        except CompareParseError as exc:
            logger.warning(
                "compare_json: chunk %d/%d failed to parse, attempting repair: %s",
                chunk_index + 1, len(chunks), exc,
                extra={"step": "compare_json_chunk_repair"},
            )
            try:
                result = _repair_json(
                    exc.raw, _get_prompt().get("schema", {}), extraction_backend
                )
            except Exception:
                logger.error(
                    "compare_json: chunk %d/%d repair also failed; %d items in this chunk "
                    "will be replaced with empty comparisons",
                    chunk_index + 1, len(chunks), len(chunk_items),
                    exc_info=True,
                    extra={"step": "compare_json_chunk_repair_failed"},
                )
                result = {"comparisons": [], "summary": ""}

        comparisons = result.get("comparisons", [])
        if not isinstance(comparisons, list):
            comparisons = []

        if len(comparisons) < len(chunk_items):
            for missing_item in chunk_items[len(comparisons) :]:
                comparisons.append(
                    {
                        "characteristic": missing_item.get("characteristic", ""),
                        "tz_value": missing_item.get("tz_value"),
                        "passport_value": missing_item.get("passport_value"),
                        "tz_quote": None,
                        "passport_quote": None,
                        "status": "not_found",
                        "note": "Сравнение не было возвращено моделью.",
                    }
                )
        if len(comparisons) > len(chunk_items):
            comparisons = comparisons[: len(chunk_items)]

        for idx, item in enumerate(chunk_items):
            # Всегда восстанавливаем поля из оригинала — LLM не должна их переименовывать
            comparisons[idx]["characteristic"] = item.get("characteristic") or (
                f"{item.get('product_name')} — {item.get('characteristic')}"
            )
            comparisons[idx]["tz_value"] = item.get("tz_value")
            comparisons[idx]["passport_value"] = item.get("passport_value")
            # Изделие паспорта и признак «это модель, которую запросил
            # пользователь» — берём из исходного item, LLM их не формирует.
            # По ним UI группирует строки и по умолчанию показывает только
            # целевую модель (плюс «Общее»).
            comparisons[idx]["product_name"] = item.get("product_name")
            # Имя изделия ТЗ — отдельно от product_name (имя изделия паспорта),
            # т.к. при N паспорт-моделей на 1 ТЗ-модель (типичный случай после
            # variant-фикса structuring) они не совпадают буквально. Нужно
            # api-gateway/фронтенду, чтобы связать строку сравнения с
            # характеристикой ТЗ по правильному ключу (см. characteristicKey
            # в pdf-analyzer) — иначе статус сопоставления не находит пару и
            # пропадает в левой панели.
            comparisons[idx]["tz_product_name"] = item.get("tz_product_name") or item.get(
                "product_name"
            )
            comparisons[idx]["is_target_model"] = item.get("is_target_model", True)
            # Если значения однозначно совпадают, всегда ставим status="confident",
            # независимо от того, что вернула LLM
            if _values_clearly_match(item.get("tz_value"), item.get("passport_value")):
                comparisons[idx]["status"] = "confident"
            # "not_found" означает "в паспорте характеристики нет вовсе" — если
            # passport_value (взят из извлечения документа, не от LLM) непуст,
            # значение в паспорте физически найдено, и "not_found" будет прямо
            # противоречить показанным пользователю данным. LLM иногда путает
            # "в ТЗ нет конкретного значения" с "в паспорте ничего нет" —
            # разворачиваем такой ответ в "uncertain" (требует проверки).
            elif comparisons[idx].get("status") == "not_found" and item.get("passport_value"):
                comparisons[idx]["status"] = "uncertain"
            # LLM иногда пишет note вида «характеристика отсутствует в паспорте»,
            # хотя passport_value/tz_value в этой же строке непустые (взяты из
            # извлечения документа, а не от LLM) — такой note противоречит данным
            # и вводит пользователя в заблуждение, поэтому убираем его.
            if _note_contradicts_value(
                comparisons[idx].get("note"), item.get("passport_value"), item.get("tz_value")
            ):
                comparisons[idx]["note"] = None
            comparisons[idx] = _attach_evidence_to_comparison(item, comparisons[idx])

        summary = result.get("summary")
        summary_text = summary.strip() if isinstance(summary, str) and summary.strip() else None
        return comparisons, summary_text

    # Чанки независимы (разные наборы characteristics, ни один не читает
    # результат другого) — обрабатываем их параллельно в потоках вместо
    # строго последовательного цикла. Каждый _compare_chunk — блокирующий
    # I/O-bound HTTP-запрос к LLM (десятки-сотни секунд ожидания ответа), не
    # CPU-bound работа, поэтому GIL не мешает реальному параллелизму здесь.
    # ThreadPoolExecutor.map сохраняет порядок результатов, соответствующий
    # порядку chunks, — важно для стабильного debug_chunk (всегда первый по
    # порядку документа, не первый завершившийся).
    indexed_chunks = [(i, c) for i, c in enumerate(chunks) if c]
    max_workers = max(1, min(settings.COMPARE_CHUNK_CONCURRENCY, len(indexed_chunks) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        chunk_results = list(executor.map(_process_chunk, indexed_chunks))

    all_comparisons: list[dict] = []
    summaries: list[str] = []
    debug_chunk: dict | None = None
    for (_, chunk_items), (comparisons, summary_text) in zip(indexed_chunks, chunk_results):
        all_comparisons.extend(comparisons)
        if debug_chunk is None:
            debug_chunk = {
                "input_items": chunk_items,
                "comparisons": comparisons,
            }
        if summary_text:
            summaries.append(summary_text)

    match_value = all(
        item.get("status") == "confident" for item in all_comparisons
    )
    mismatches = [c for c in all_comparisons if c.get("status") != "confident"]
    summary_text = " ".join(summaries).strip()
    result_payload = {
        "match": match_value,
        "summary": summary_text,
        "comparisons": all_comparisons,
        "char_name_aliases": char_name_aliases,
    }
    if debug_chunk is not None:
        result_payload["debug_chunk"] = debug_chunk
    logger.info(
        "compare_json finished in %.2fs: comparisons=%d mismatches=%d match=%s",
        time.monotonic() - started_at, len(all_comparisons), len(mismatches), match_value,
        extra={"step": "compare_json_finished"},
    )
    return result_payload
