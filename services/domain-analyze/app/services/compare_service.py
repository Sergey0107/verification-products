import json
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.knowledge_base_client import list_canonical_attributes, search_knowledge


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
    extraction = data.get("extraction") if "extraction" in data else data
    if not isinstance(extraction, dict):
        return []
    products = extraction.get("products")
    if not isinstance(products, list):
        products = _collect_products_from_pages(extraction.get("pages"))
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
    if all(key in bbox for key in ("x", "y", "width", "height")):
        try:
            return {
                "x": float(bbox["x"]),
                "y": float(bbox["y"]),
                "width": float(bbox["width"]),
                "height": float(bbox["height"]),
            }
        except (TypeError, ValueError):
            return None
    if all(key in bbox for key in ("x0", "y0", "x1", "y1")):
        try:
            x0 = float(bbox["x0"])
            y0 = float(bbox["y0"])
            x1 = float(bbox["x1"])
            y1 = float(bbox["y1"])
        except (TypeError, ValueError):
            return None
        return {"x": x0, "y": y0, "width": max(0.0, x1 - x0), "height": max(0.0, y1 - y0)}
    if all(key in bbox for key in ("left", "top", "right", "bottom")):
        try:
            left = float(bbox["left"])
            top = float(bbox["top"])
            right = float(bbox["right"])
            bottom = float(bbox["bottom"])
        except (TypeError, ValueError):
            return None
        return {
            "x": left,
            "y": top,
            "width": max(0.0, right - left),
            "height": max(0.0, bottom - top),
        }
    return None


def _derive_matched_terms(*parts: Any) -> list[str]:
    tokens: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        tokens.extend(re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9./-]{1,}", part))
    return _dedupe_strings(tokens[:8])


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
    }


def _normalize_reference_span(reference: Any, fallback_quote: str | None) -> dict[str, Any] | None:
    if isinstance(reference, dict):
        bbox = _infer_bbox(reference.get("bbox"))
        page = reference.get("page")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        if not isinstance(page, int) or page <= 0:
            page = _extract_page_number(str(reference.get("locator_text") or reference.get("anchor_text") or ""))
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
        return _build_span_payload(
            fragment_type=fragment_type,
            locator_strategy=str(locator_strategy),
            page_number=page,
            anchor_text=anchor_text,
            quote_text=quote_text,
            locator_text=locator_text,
            bbox=bbox,
            confidence=float(confidence),
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


def _build_evidence_payload(
    *,
    document_type: str,
    references: list[Any],
    quote: str | None,
    value: Any,
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
    fallback_quote = quote or (str(value) if value is not None else None)
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

    if len(tz_products) == 1 and len(passport_products) > 1:
        tz_baseline = tz_products[0]
        tz_baseline_name = tz_baseline.get("product_name") or "Неизвестное изделие"
        tz_chars_map = tz_map.get(tz_baseline_name, {})
        tz_chars_list = tz_product_chars.get(tz_baseline_name, [])
        for passport_product in passport_products:
            product_name = passport_product.get("product_name") or "Неизвестное изделие"
            passport_chars_map = passport_map.get(product_name, {})
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


def _attach_evidence_to_comparison(item: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    tz_quote = comparison.get("tz_quote")
    passport_quote = comparison.get("passport_quote")
    comparison["tz_evidence"] = _build_evidence_payload(
        document_type="tz",
        references=item.get("tz_references", []),
        quote=tz_quote if isinstance(tz_quote, str) else None,
        value=item.get("tz_value"),
    )
    comparison["passport_evidence"] = _build_evidence_payload(
        document_type="passport",
        references=item.get("passport_references", []),
        quote=passport_quote if isinstance(passport_quote, str) else None,
        value=item.get("passport_value"),
    )
    return comparison


def _chunk(items: list[dict], size: int) -> list[list[dict]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _compare_chunk(items: list[dict]) -> dict:
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
        "temperature": 0.0,
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


def _build_kb_prompt_appendix(items: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    try:
        attributes = list_canonical_attributes()
    except Exception:
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


def _repair_json(raw_text: str, schema: dict) -> dict:
    system_message = (
        "Ты — валидатор JSON. Преобразуй входной текст в валидный JSON, "
        "строго соответствующий схеме. Верни ТОЛЬКО JSON без пояснений."
    )
    user_message = json.dumps(
        {"schema": schema, "raw": raw_text},
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
        "temperature": 0.0,
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
    return _extract_json(content)


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
    debug_chunk: dict | None = None

    for chunk_items in chunks:
        if not chunk_items:
            continue
        try:
            result = _compare_chunk(chunk_items)
        except CompareParseError as exc:
            try:
                result = _repair_json(exc.raw, _get_prompt().get("schema", {}))
            except Exception:
                result = {"comparisons": [], "summary": ""}

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
            comparisons[idx] = _attach_evidence_to_comparison(item, comparisons[idx])
        all_comparisons.extend(comparisons)
        if debug_chunk is None:
            debug_chunk = {
                "input_items": chunk_items,
                "comparisons": comparisons,
            }
        delay_seconds = settings.COMPARE_CHUNK_DELAY_SECONDS
        if delay_seconds and delay_seconds > 0:
            time.sleep(delay_seconds)
        summary = result.get("summary")
        if isinstance(summary, str) and summary.strip():
            summaries.append(summary.strip())

    match_value = all(
        item.get("is_match") is True for item in all_comparisons
    )
    summary_text = " ".join(summaries).strip()
    result_payload = {
        "match": match_value,
        "summary": summary_text,
        "comparisons": all_comparisons,
    }
    if debug_chunk is not None:
        result_payload["debug_chunk"] = debug_chunk
    return result_payload
