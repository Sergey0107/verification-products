import json
import logging
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


def _build_knowledge_base_prompt_appendix(file_type: str) -> str:
    if file_type not in {"tz", "passport"}:
        return ""

    sections: list[str] = []
    try:
        attributes = list_canonical_attributes()
    except Exception:
        attributes = []
    if attributes:
        lines = ["Канонические технические атрибуты из Knowledge Base:"]
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
    return "\n\nИспользуй следующую Knowledge Base как источник истины для нормализации характеристик и терминов:\n" + "\n\n".join(sections)


def _build_target_characteristics_appendix(
    file_type: str,
    target_characteristics: list[dict] | None,
) -> str:
    if file_type != "passport" or not target_characteristics:
        return ""

    compact_items = []
    for item in target_characteristics:
        if not isinstance(item, dict):
            continue
        compact_items.append(
            {
                "product_name": item.get("product_name"),
                "name": item.get("name"),
                "value": item.get("value"),
            }
        )
    if not compact_items:
        return ""

    targets_json = json.dumps(compact_items, ensure_ascii=False, indent=2)
    return (
        "\n\nPassport extraction scope:\n"
        "Extract only the characteristics listed below. Do not extract unrelated passport "
        "characteristics. Keep the existing JSON schema with products and characteristics. "
        "For each target, find the corresponding value in the passport and preserve references/evidence "
        "when available. If a target is not present in the passport, omit it rather than adding unrelated data.\n"
        f"Target TZ characteristics:\n{targets_json}"
    )


def build_s3_url(storage_key: str) -> str:
    endpoint = settings.S3_ENDPOINT.rstrip("/")
    bucket = settings.BUCKET_NAME.strip()
    return f"{endpoint}/{bucket}/{storage_key.lstrip('/')}"


def run_extraction_task(
    analysis_id: str,
    file_id: str,
    file_type: str,
    storage_path: str,
    storage_url: str | None = None,
    extraction_backend: str | None = None,
    target_characteristics: list[dict] | None = None,
) -> None:
    file_type = (file_type or "").lower()
    if not storage_path:
        raise ValueError(f"Missing storage_path for file {file_id}")

    if storage_url:
        file_url = storage_url
    else:
        if not settings.BUCKET_NAME:
            raise ValueError("BUCKET_NAME is not set; cannot build S3 URL")
        file_url = build_s3_url(storage_path)

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
