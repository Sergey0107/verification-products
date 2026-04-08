from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, desc, select, text
from sqlalchemy.orm import Session

from app.db.models import KnowledgeChunk, NormativeSource
from app.db.session import is_postgres
from app.services.embeddings import cosine_similarity, embed_text, normalize_text, tokenize


def _query_tokens(value: str) -> list[str]:
    return [token for token in tokenize(value) if len(token) >= 2]


def _lexical_score(query: str, source: NormativeSource, chunk: KnowledgeChunk) -> float:
    normalized_query = normalize_text(query)
    query_tokens = _query_tokens(query)
    if not normalized_query or not query_tokens:
        return 0.0

    search_haystack = normalize_text(
        " ".join(
            filter(
                None,
                [
                    source.title,
                    source.summary,
                    chunk.text,
                    source.source_key,
                ],
            )
        )
    )
    if not search_haystack:
        return 0.0

    chunk_tokens = set(tokenize(search_haystack))
    overlap = [token for token in query_tokens if token in chunk_tokens]
    if not overlap and normalized_query not in search_haystack:
        return 0.0

    overlap_ratio = len(set(overlap)) / max(1, len(set(query_tokens)))
    phrase_bonus = 0.35 if normalized_query in search_haystack else 0.0
    return min(1.0, overlap_ratio + phrase_bonus)


def _hybrid_score(query: str, source: NormativeSource, chunk: KnowledgeChunk, semantic_score: float) -> float:
    lexical_score = _lexical_score(query, source, chunk)
    if lexical_score <= 0:
        return 0.0
    return round((semantic_score * 0.45) + (lexical_score * 0.55), 6)


def search_chunks(
    db: Session,
    *,
    query: str,
    limit: int = 5,
    project_key: str | None = None,
    source_type: str | None = None,
    effective_on: date | None = None,
    published_only: bool = True,
) -> list[dict[str, Any]]:
    if not _query_tokens(query):
        return []

    query_embedding = embed_text(query)
    stmt: Select[Any] = select(KnowledgeChunk, NormativeSource).join(
        NormativeSource,
        NormativeSource.id == KnowledgeChunk.source_id,
    )
    if project_key:
        stmt = stmt.where(
            KnowledgeChunk.project_key == project_key,
            NormativeSource.project_key == project_key,
        )
    if source_type:
        stmt = stmt.where(NormativeSource.source_type == source_type)
    if published_only:
        stmt = stmt.where(
            KnowledgeChunk.is_published.is_(True),
            NormativeSource.is_published.is_(True),
        )
    if effective_on:
        stmt = stmt.where(
            (NormativeSource.effective_from.is_(None) | (NormativeSource.effective_from <= effective_on)),
            (NormativeSource.effective_to.is_(None) | (NormativeSource.effective_to >= effective_on)),
        )

    if is_postgres():
        vector_literal = "[" + ",".join(f"{float(item):.8f}" for item in query_embedding) + "]"
        stmt = (
            stmt.order_by(text("knowledge_chunks.embedding <=> CAST(:query_embedding AS vector)"))
            .limit(max(limit * 8, 20))
            .params(query_embedding=vector_literal)
        )
        rows = db.execute(stmt).all()
        results = []
        for chunk, source in rows:
            semantic_score = cosine_similarity(query_embedding, chunk.embedding)
            score = _hybrid_score(query, source, chunk, semantic_score)
            if score <= 0:
                continue
            results.append(_serialize_result(source, chunk, score))
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    rows = db.execute(stmt.order_by(desc(KnowledgeChunk.created_at))).all()
    scored = []
    for chunk, source in rows:
        semantic_score = cosine_similarity(query_embedding, chunk.embedding)
        score = _hybrid_score(query, source, chunk, semantic_score)
        if score <= 0:
            continue
        scored.append(_serialize_result(source, chunk, score))
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _serialize_result(source: NormativeSource, chunk: KnowledgeChunk, score: float) -> dict[str, Any]:
    return {
        "project_key": source.project_key,
        "source_id": source.id,
        "source_key": source.source_key,
        "source_version": source.version,
        "source_title": source.title,
        "source_type": source.source_type,
        "status": source.status,
        "effective_from": source.effective_from.isoformat() if source.effective_from else None,
        "effective_to": source.effective_to.isoformat() if source.effective_to else None,
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "score": round(float(score), 6),
    }
