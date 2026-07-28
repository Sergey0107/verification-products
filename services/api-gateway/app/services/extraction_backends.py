from app.core.config import settings

SUPPORTED_EXTRACTION_BACKENDS = (
    "openrouter", "llamaparse", "mineru", "pdfplumber", "paddleocr_vl", "yandex_vision_ocr",
)
EXTRACTION_BACKEND_LABELS = {
    "openrouter": "AI Tunnel",
    "llamaparse": "LlamaParse + AI Tunnel",
    "mineru": "MinerU + AI Tunnel",
    "pdfplumber": "pdfplumber (точная геометрия) + AI Tunnel",
    "paddleocr_vl": "PaddleOCR-VL (GPU) + Yandex AI Studio",
    "yandex_vision_ocr": "Yandex Vision OCR + Yandex AI Studio",
}


def normalize_extraction_backend(backend: str | None) -> str:
    normalized = (backend or settings.EXTRACTION_BACKEND or "openrouter").strip().lower()
    if normalized not in SUPPORTED_EXTRACTION_BACKENDS:
        return settings.EXTRACTION_BACKEND
    return normalized


def extraction_backend_label(backend: str | None) -> str:
    normalized = normalize_extraction_backend(backend)
    return EXTRACTION_BACKEND_LABELS.get(normalized, normalized)
