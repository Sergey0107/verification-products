"""Построение evidence-объекта (формат BackendEvidence) для характеристик,
добавленных пользователем вручную путём выделения области в PDF мышью —
в отличие от LLM-извлечённых, здесь координаты и текст заданы человеком
напрямую, поэтому evidence всегда содержит ровно один exact_span с
confidence=1.0 и bbox в виде {left, top, right, bottom} (0..1 normalized)."""

from __future__ import annotations


def build_manual_evidence(
    *,
    document_type: str,
    value: str | None,
    page: int,
    bbox: list[float] | tuple[float, float, float, float],
    quote_origin: str,
) -> dict:
    left, top, right, bottom = bbox
    span = {
        "fragment_type": "exact_span",
        "locator_strategy": "manual_selection",
        "page_number": page,
        "page": page,
        "anchor_text": value,
        "quote_text": value,
        "locator_text": value,
        "bbox": {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "x0": left,
            "y0": top,
            "x1": right,
            "y1": bottom,
            "norm_x0": left,
            "norm_y0": top,
            "norm_x1": right,
            "norm_y1": bottom,
        },
        "confidence": 1.0,
        "position_unverified": False,
    }
    return {
        "evidence_version": "v2",
        "document_type": document_type,
        "position_status": "exact_span",
        "locator_strategy": "manual_selection",
        "display_quote": value,
        "full_quote": value,
        "fallback_quote": value,
        "quote_origin": quote_origin,
        "matched_terms": [value] if value else [],
        "confidence": 1.0,
        "source_spans": [span],
        "page_anchors": [{"page_number": page, "page": page, "label": f"Страница {page}"}],
        "active_span": span,
        "exact_span": span,
        "text_anchor": None,
        "page_anchor": span,
        "navigation_target": span,
    }


def manual_references_payload(
    *, value: str | None, page: int, bbox: list[float] | tuple[float, float, float, float]
) -> list[dict]:
    """Формат references[] как в сыром LLM-выводе — нужен для TzCharacteristicReview.references,
    чтобы ручные ТЗ-характеристики выглядели идентично извлечённым для остального кода."""
    left, top, right, bottom = bbox
    return [
        {
            "page": page,
            "quote_text": value,
            "anchor_text": value,
            "locator_text": value,
            "locator_strategy": "manual_selection",
            "confidence": 1.0,
            "position_unverified": False,
            "bbox": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "x0": left,
                "y0": top,
                "x1": right,
                "y1": bottom,
                "norm_x0": left,
                "norm_y0": top,
                "norm_x1": right,
                "norm_y1": bottom,
            },
        }
    ]
