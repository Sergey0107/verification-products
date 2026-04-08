from app.core.config import settings

SUPPORTED_EXTRACTION_BACKENDS = ("openrouter", "llamaparse")
EXTRACTION_BACKEND_LABELS = {
    "openrouter": "OpenRouter",
    "llamaparse": "LlamaParse + OpenRouter",
}


def normalize_extraction_backend(backend: str | None) -> str:
    normalized = (backend or settings.EXTRACTION_BACKEND or "openrouter").strip().lower()
    if normalized not in SUPPORTED_EXTRACTION_BACKENDS:
        return settings.EXTRACTION_BACKEND
    return normalized


def extraction_backend_label(backend: str | None) -> str:
    normalized = normalize_extraction_backend(backend)
    return EXTRACTION_BACKEND_LABELS.get(normalized, normalized)
