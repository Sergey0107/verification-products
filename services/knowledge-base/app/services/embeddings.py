from __future__ import annotations

import hashlib
import math
import re

from app.core.config import settings


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9./_-]{1,}")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower().replace("ё", "е"))


def tokenize(value: str | None) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    return TOKEN_RE.findall(normalized)


def embed_text(value: str | None) -> list[float]:
    dim = settings.KNOWLEDGE_BASE_EMBEDDING_DIM
    vector = [0.0] * dim
    tokens = tokenize(value)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[slot] += sign * weight

    norm = math.sqrt(sum(component * component for component in vector))
    if norm <= 1e-9:
        return vector
    return [round(component / norm, 8) for component in vector]


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))
