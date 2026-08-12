"""Конвертация сырого ответа paddleocr-vl-service ({"paddle": ..., "yandex": ...})
в формат result_payload, ожидаемый postprocess_extraction_result/_finalize_extraction
(result.products[], extraction.pages[], extraction_metadata).

Копия логики из extraction/app/main.py (_paddleocr_vl_specs_to_products,
_paddle_bbox_to_reference_bbox, _build_result_page) — синхронный путь делает эту
конвертацию внутри extraction-service до возврата ответа api-gateway, но
async-путь (backend yandex_vision_ocr) получает сырой результат напрямую от
paddleocr-vl-service через callback на /internal/extraction-callback, минуя
extraction-service целиком, поэтому та же конвертация нужна и здесь."""

from typing import Any


def _paddle_bbox_to_reference_bbox(
    bbox_px: list[float], page_width: float, page_height: float
) -> dict[str, float]:
    x0, y0, x1, y1 = bbox_px
    return {
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "left": x0, "top": y0, "right": x1, "bottom": y1,
        "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0,
        "norm_x0": x0 / page_width, "norm_y0": y0 / page_height,
        "norm_x1": x1 / page_width, "norm_y1": y1 / page_height,
    }


def _paddleocr_vl_specs_to_products(
    specifications: list[dict[str, Any]], paddle_pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    page_dims: dict[int, tuple[float, float]] = {}
    for idx, page in enumerate(paddle_pages):
        pruned = (page or {}).get("prunedResult") or {}
        width, height = pruned.get("width"), pruned.get("height")
        if width and height:
            page_dims[idx] = (float(width), float(height))

    products_by_variant: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for spec in specifications:
        variant = spec.get("variant") or "Общее"
        if variant not in products_by_variant:
            products_by_variant[variant] = {"product_name": variant, "characteristics": []}
            order.append(variant)

        value = spec.get("value") or ""
        unit = spec.get("unit")
        value_text = f"{value} {unit}".strip() if unit else value

        source = spec.get("source") or {}
        page_index = source.get("page_index")
        blocks = source.get("blocks") or []

        references: list[dict[str, Any]] = []
        for block in blocks:
            block_bbox = block.get("precise_bbox") or block.get("block_bbox")
            if block_bbox is None or page_index is None:
                continue
            dims = page_dims.get(page_index)
            reference: dict[str, Any] = {
                # +1: paddleocr-vl-service использует 0-based page_index,
                # ivolga (references[].page) ожидает 1-based.
                "page": page_index + 1,
                "page_number": page_index + 1,
                "quote_text": value,
                "anchor_text": spec.get("name"),
                "matched_text": value,
                "locator_strategy": "bbox",
                "geometry_source": "paddleocr_vl",
                "position_unverified": False,
            }
            if dims is not None:
                reference["bbox"] = _paddle_bbox_to_reference_bbox(block_bbox, *dims)
            references.append(reference)

        products_by_variant[variant]["characteristics"].append(
            {
                "name": spec.get("name"),
                "value": value_text,
                "references": references,
            }
        )

    return [products_by_variant[v] for v in order]


def _build_result_page(
    extracted_data: dict[str, Any],
    *,
    raw_text: str | None = None,
    page_no: int = 1,
) -> dict[str, Any]:
    return {
        "page_no": page_no,
        "extracted_data": extracted_data,
        "raw_text": raw_text,
        "errors": None,
    }


def convert_paddleocr_vl_callback_result(
    raw_result: dict[str, Any],
    *,
    analysis_id: str,
    file_id: str,
    file_type: str,
    ocr_provider: str = "yandex_vision",
) -> dict[str, Any]:
    """Конвертирует {"paddle": ..., "yandex": ...} (как его кладёт job_queue.py
    в JobRecord.result на стороне paddleocr-vl-service) в формат, ожидаемый
    postprocess_extraction_result/_finalize_extraction."""
    paddle_pages = (raw_result.get("paddle") or {}).get("pages") or []
    yandex_result = raw_result.get("yandex") or {}
    specifications = yandex_result.get("specifications") or []

    products = _paddleocr_vl_specs_to_products(specifications, paddle_pages)

    return {
        "analysis_id": analysis_id,
        "file_id": file_id,
        "file_type": file_type,
        "backend": "yandex_vision_ocr",
        "model_parse": ocr_provider,
        "model_extract": "yandex-deepseek-v4-flash",
        "result": {"products": products},
        "extraction": {"pages": [_build_result_page({"products": products})]},
        "extraction_metadata": {
            "docling_version": None,
            "page_count": len(paddle_pages),
            "errors": [],
            "provider": f"paddleocr-vl-service/{ocr_provider}",
            "provider_usage": None,
            "geometry": {
                "enabled": True,
                "provider": "paddleocr_vl_precise_locator",
                "applied": True,
                "page_count": len(paddle_pages),
            },
            "ocr_provider": ocr_provider,
            "pages_processed": yandex_result.get("pages_processed"),
            "pages_failed": yandex_result.get("pages_failed"),
            "has_text_layer": yandex_result.get("has_text_layer"),
            "ocr_fallback_used": yandex_result.get("ocr_fallback_used"),
            "docx_conversion": None,
        },
    }
