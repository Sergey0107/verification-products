from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


def _get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=settings.KNOWLEDGE_BASE_TIMEOUT_SECONDS) as client:
        response = client.get(f"{settings.KNOWLEDGE_BASE_URL.rstrip('/')}{path}", params=params)
    response.raise_for_status()
    return response.json()


def list_canonical_attributes() -> list[dict[str, Any]]:
    payload = _get("/canonical-attributes", params={"project_key": "technical_compliance"})
    return payload if isinstance(payload, list) else []


def search_knowledge(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    payload = _get(
        "/retrieval/search",
        params={"q": query, "limit": limit, "project_key": "technical_compliance"},
    )
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return []
