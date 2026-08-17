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


# Строки, которыми LLM обозначает "значения нет". Приходят как обычный текст и
# без отсева доезжают до интерфейса в виде "None кВт" рядом с настоящими
# значениями (15% строк сравнения на реальном анализе aca90496).
_EMPTY_VALUE_TOKENS = {"none", "null", "n/a", "na", "nan", "-", "—", "–", ""}


def _clean_value(value: Any) -> str:
    """Значение характеристики, где "пустышки" от LLM приведены к пустой строке."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_VALUE_TOKENS else text


def _spec_page_index(spec: dict[str, Any]) -> int | None:
    """Номер страницы, на которой найдена характеристика (0-based, как отдаёт
    paddleocr-vl-service). None, если источник не проставлен."""
    source = spec.get("source") or {}
    page_index = source.get("page_index")
    return page_index if isinstance(page_index, int) else None


def _build_page_variant_map(
    specifications: list[dict[str, Any]],
) -> dict[int, str]:
    """Карта "страница -> изделие" по характеристикам, у которых variant задан
    явно. Страница-якорь попадает в карту, только если ВСЕ её
    variant-размеченные характеристики принадлежат одному изделию:
    страница-переход, где встречаются метки сразу двух моделей, якорем не
    становится — там безопаснее старое поведение (дублирование), чем угадывание.

    От якорей принадлежность РАСПРОСТРАНЯЕТСЯ на последующие страницы до
    следующего якоря: в каталоге изделие описано разделом на несколько
    страниц, а явный заголовок модели (единственный источник variant для LLM)
    стоит только на первой странице раздела. Без этого середина раздела
    оставалась бы вне карты — именно так "Мощность электродвигателя 18,5 кВт"
    со стр. 2 попадала в оба изделия, хотя стр. 2 относится к разделу первой
    модели (якорь на стр. 1), а 7,5 кВт со стр. 5 — к разделу второй
    (якорь на стр. 4).

    Страницы ДО первого якоря намеренно остаются вне карты (общая шапка
    документа, титульный лист — они не принадлежат конкретному изделию).
    Пустая карта = документ не даёт сигнала о разделении по страницам, и
    поведение остаётся ровно таким, каким было до этой доработки."""
    variants_per_page: dict[int, set[str]] = {}
    for spec in specifications:
        variant = spec.get("variant")
        page_index = _spec_page_index(spec)
        if not variant or page_index is None:
            continue
        variants_per_page.setdefault(page_index, set()).add(variant)

    anchors = {
        page_index: next(iter(variants))
        for page_index, variants in variants_per_page.items()
        if len(variants) == 1
    }
    if not anchors:
        return {}

    max_page = max(
        [p for p in (_spec_page_index(s) for s in specifications) if p is not None]
        or [max(anchors)]
    )

    page_variants: dict[int, str] = {}
    current: str | None = None
    for page_index in range(max_page + 1):
        if page_index in anchors:
            current = anchors[page_index]
        elif page_index in variants_per_page:
            # Страница с метками сразу нескольких моделей — граница раздела,
            # не наследуем ничего до следующего однозначного якоря.
            current = None
        if current is not None:
            page_variants[page_index] = current
    return page_variants


def _pick_single_product_name(specifications: list[dict[str, Any]]) -> str | None:
    """Имя единственного изделия документа среди размеченных LLM вариантов.

    Берём вариант с наибольшим числом характеристик: настоящее изделие описано
    десятками строк, а фантомы — единицами. На реальном ТЗ насоса НП-1 LLM
    выделила четыре "изделия": НП-1 (168 характеристик) и мусорные Мр.20 (15),
    Мр.25 (15), 'A' (25) — маркировки металлорукавов из строки про кабельные
    вводы и буква с чертежа. None, если вариантов нет вовсе."""
    counts: dict[str, int] = {}
    for spec in specifications:
        variant = spec.get("variant")
        if isinstance(variant, str) and variant.strip():
            counts[variant] = counts.get(variant, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _paddleocr_vl_specs_to_products(
    specifications: list[dict[str, Any]],
    paddle_pages: list[dict[str, Any]],
    *,
    single_product: bool = False,
) -> list[dict[str, Any]]:
    """Группирует specs по variant в products. Характеристики БЕЗ variant (общие,
    не привязанные к конкретной модели) никогда не образуют отдельный продукт
    "Общее" — они приписываются к уже известным именованным моделям:

    1) если именованная модель ровно одна — общие характеристики уходят в неё;
    2) если моделей несколько (каталог паспорта на 2+ изделия) — характеристика
       уходит в ту модель, к которой относится СТРАНИЦА, на которой она найдена
       (см. _build_page_variant_map): в каталогах разные изделия описаны
       разными разделами/страницами, поэтому страница — надёжный признак
       принадлежности. Дублирование в КАЖДУЮ модель остаётся только как
       fallback, когда страница неизвестна или на ней нет ни одной
       variant-размеченной характеристики;
    3) если именованных моделей нет вовсе, общие характеристики образуют
       единственный безымянный продукт (product_name=None).

    Реальный инцидент (2026-08-13): паспорт-каталог на КМХ (В 6,45) 50-50 и
    КМХ (В 3,00) 12,5-50 — LLM разметила variant лишь у 17 характеристик из
    128, остальные 111 пришли с variant=null и дублировались в ОБА изделия.
    В сравнение с ТЗ попадали чужие значения (мощность 18,5 кВт от первой
    модели оказывалась и у второй). При этом привязка по странице разделяет
    их точно: уникальные характеристики первой модели были только на стр. 1,
    второй — только на стр. 4."""
    page_dims: dict[int, tuple[float, float]] = {}
    for idx, page in enumerate(paddle_pages):
        pruned = (page or {}).get("prunedResult") or {}
        width, height = pruned.get("width"), pruned.get("height")
        if width and height:
            page_dims[idx] = (float(width), float(height))

    if single_product:
        # Документ описывает ровно одно изделие (ТЗ). Разметка вариантов от
        # LLM здесь не структура каталога, а шум: маркировки комплектующих и
        # обрывки чертежей становились отдельными "изделиями", и их
        # характеристики выпадали из сравнения целиком.
        single_name = _pick_single_product_name(specifications)
        named_variants: list[str] = [single_name] if single_name else []
        page_variants: dict[int, str] = {}
    else:
        named_variants = []
        for spec in specifications:
            variant = spec.get("variant")
            if variant and variant not in named_variants:
                named_variants.append(variant)

        page_variants = _build_page_variant_map(specifications)

    products_by_variant: dict[str | None, dict[str, Any]] = {}
    order: list[str | None] = []

    def _ensure_product(key: str | None) -> dict[str, Any]:
        if key not in products_by_variant:
            products_by_variant[key] = {"product_name": key, "characteristics": []}
            order.append(key)
        return products_by_variant[key]

    for spec in specifications:
        variant = spec.get("variant")
        if single_product:
            # Всё изделие целиком — одна карточка, вне зависимости от variant.
            target_keys = named_variants or [None]
        elif variant:
            target_keys = [variant]
        elif len(named_variants) > 1:
            # Каталог на несколько изделий: привязываем к изделию своей
            # страницы; дублируем во все модели только если страница ничего
            # не говорит о принадлежности (см. _build_page_variant_map).
            page_variant = page_variants.get(_spec_page_index(spec))
            target_keys = [page_variant] if page_variant else list(named_variants)
        else:
            target_keys = named_variants or [None]

        value = _clean_value(spec.get("value"))
        unit = spec.get("unit")
        # Единица без значения — мусор ("None кВт"): приклеиваем только к
        # непустому значению.
        value_text = f"{value} {unit}".strip() if (unit and value) else value

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

        for key in target_keys:
            product = _ensure_product(key)
            product["characteristics"].append(
                {
                    "name": spec.get("name"),
                    "value": value_text,
                    "references": list(references),
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

    # ТЗ — заказ на ОДНО изделие: все его характеристики относятся к нему,
    # даже если LLM разметила часть строк "вариантами" (см. single_product).
    products = _paddleocr_vl_specs_to_products(
        specifications, paddle_pages, single_product=(file_type == "tz")
    )

    return {
        "analysis_id": analysis_id,
        "file_id": file_id,
        "file_type": file_type,
        "backend": "yandex_vision_ocr",
        "model_parse": ocr_provider,
        "model_extract": "yandex-deepseek-v4-flash",
        "result": {"products": products},
        "extraction": {"pages": [_build_result_page({"products": products})]},
        # Сырой callback-payload ДО конвертации в products — см. тот же ключ
        # в extraction/app/main.py::_extract_via_paddleocr_vl (синхронный
        # путь). postprocess_extraction_result вырезает его в отдельный файл
        # на диске и не даёт попасть в ExtractionResult.payload.
        "raw_ocr": raw_result,
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
