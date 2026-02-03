import json
from typing import Any

import httpx

from app.core.config import settings


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


def _normalize_products(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    extraction = data.get("extraction") if "extraction" in data else data
    if not isinstance(extraction, dict):
        return []
    products = extraction.get("products", [])
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


def _ordered_products(tz_products: list[dict], passport_products: list[dict]) -> list[dict]:
    ordered = []
    seen = set()
    for item in tz_products:
        name = item.get("product_name") or "Неизвестное изделие"
        if name not in seen:
            ordered.append(item)
            seen.add(name)
    for item in passport_products:
        name = item.get("product_name") or "Неизвестное изделие"
        if name not in seen:
            ordered.append(item)
            seen.add(name)
    return ordered


def _build_char_map(products: list[dict]) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for product in products:
        product_name = product.get("product_name") or "Неизвестное изделие"
        result.setdefault(product_name, {})
        for item in product.get("characteristics", []):
            name = item.get("name")
            if not name:
                continue
            result[product_name][name] = {
                "value": item.get("value"),
                "references": item.get("references", []),
            }
    return result


def _ordered_characteristics(
    tz_chars: list[dict], passport_chars: list[dict]
) -> list[str]:
    ordered = []
    seen = set()
    for item in tz_chars:
        name = item.get("name")
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    for item in passport_chars:
        name = item.get("name")
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def _build_comparison_items(tz_data: dict, passport_data: dict) -> list[dict]:
    tz_products = _normalize_products(tz_data)
    passport_products = _normalize_products(passport_data)
    ordered_products = _ordered_products(tz_products, passport_products)

    tz_map = _build_char_map(tz_products)
    passport_map = _build_char_map(passport_products)

    tz_product_chars = {
        item.get("product_name") or "Неизвестное изделие": item.get("characteristics", [])
        for item in tz_products
    }
    passport_product_chars = {
        item.get("product_name") or "Неизвестное изделие": item.get("characteristics", [])
        for item in passport_products
    }

    items: list[dict] = []
    for product in ordered_products:
        product_name = product.get("product_name") or "Неизвестное изделие"
        tz_chars_map = tz_map.get(product_name, {})
        passport_chars_map = passport_map.get(product_name, {})
        tz_chars_list = tz_product_chars.get(product_name, [])
        passport_chars_list = passport_product_chars.get(product_name, [])
        ordered_char_names = _ordered_characteristics(
            tz_chars_list, passport_chars_list
        )

        for char_name in ordered_char_names:
            tz_entry = tz_chars_map.get(char_name, {})
            passport_entry = passport_chars_map.get(char_name, {})
            items.append(
                {
                    "product_name": product_name,
                    "characteristic": char_name,
                    "tz_value": tz_entry.get("value"),
                    "passport_value": passport_entry.get("value"),
                    "tz_references": tz_entry.get("references", []),
                    "passport_references": passport_entry.get("references", []),
                }
            )
    return items


def _chunk(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _compare_chunk(items: list[dict]) -> dict:
    prompt_payload = _get_prompt()
    prompt_text = prompt_payload.get("prompt", "")
    schema = prompt_payload.get("schema", {})

    system_message = (
        f"{prompt_text}\n\nReturn JSON that matches this schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    user_message = json.dumps(
        {"comparison_items": items},
        ensure_ascii=False,
    )

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
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
    try:
        return _extract_json(content)
    except json.JSONDecodeError as exc:
        raise CompareParseError(str(exc), content)


def compare_json(tz_data: dict, passport_data: dict) -> dict:
    items = _build_comparison_items(tz_data, passport_data)
    if not items:
        return {
            "match": False,
            "summary": "Нет данных для сравнения.",
            "comparisons": [],
        }

    chunk_size = settings.COMPARE_CHUNK_SIZE
    chunks = _chunk(items, chunk_size)

    all_comparisons: list[dict] = []
    summaries: list[str] = []

    for chunk_items in chunks:
        result = _compare_chunk(chunk_items)
        comparisons = result.get("comparisons", [])
        if not isinstance(comparisons, list):
            comparisons = []

        if len(comparisons) < len(chunk_items):
            for missing_item in chunk_items[len(comparisons) :]:
                comparisons.append(
                    {
                        "characteristic": f"{missing_item.get('product_name')} — {missing_item.get('characteristic')}",
                        "tz_value": missing_item.get("tz_value"),
                        "passport_value": missing_item.get("passport_value"),
                        "tz_quote": None,
                        "passport_quote": None,
                        "is_match": False,
                        "note": "Сравнение не было возвращено моделью.",
                    }
                )
        if len(comparisons) > len(chunk_items):
            comparisons = comparisons[: len(chunk_items)]

        for idx, item in enumerate(chunk_items):
            if not comparisons[idx].get("characteristic"):
                comparisons[idx]["characteristic"] = (
                    f"{item.get('product_name')} — {item.get('characteristic')}"
                )
        all_comparisons.extend(comparisons)
        summary = result.get("summary")
        if isinstance(summary, str) and summary.strip():
            summaries.append(summary.strip())

    match_value = all(
        item.get("is_match") is True for item in all_comparisons
    )
    summary_text = " ".join(summaries).strip()
    return {
        "match": match_value,
        "summary": summary_text,
        "comparisons": all_comparisons,
    }
