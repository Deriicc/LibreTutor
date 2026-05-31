"""VectorSearch — PDF chunking + embedding + retrieval (RAG context for chat).

Embedding strategy (issue 19): if `EMBEDDING_API_KEY` is set in env, route
to an OpenAI-compatible `/embeddings` endpoint (default model Aliyun
DashScope `text-embedding-v4`, 1024-dim native). Otherwise fall back to the
deterministic hash-based embedding — captures lexical overlap but no
semantics. The rest of the pipeline doesn't change either way.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
import uuid

import fitz  # type: ignore[import-untyped]
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import DocumentChunk
from app.models.document_chunk import EMBEDDING_DIM
from app.user_llm import resolve_embedding

logger = logging.getLogger(__name__)


# ---------- chunking ----------


CHUNK_CHARS = 600
CHUNK_OVERLAP = 100


def chunk_pdf_by_chars(
    pdf_path: str, *, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[dict]:
    """Walk the PDF page by page; for each page, slide a window of `chunk_chars`
    with `overlap` over the text. Returns list of {text, page_start, page_end}."""
    doc = fitz.open(pdf_path)
    try:
        out: list[dict] = []
        for page_idx in range(doc.page_count):
            page_text = doc[page_idx].get_text()
            page_text = re.sub(r"\s+", " ", page_text).strip()
            if not page_text:
                continue
            page_no = page_idx + 1  # 1-based
            i = 0
            while i < len(page_text):
                end = min(i + chunk_chars, len(page_text))
                slice_text = page_text[i:end].strip()
                if slice_text:
                    out.append(
                        {
                            "text": slice_text,
                            "page_start": page_no,
                            "page_end": page_no,
                        }
                    )
                if end >= len(page_text):
                    break
                i = end - overlap
                if i <= 0:
                    i = end
        return out
    finally:
        doc.close()


def chunk_pdf_cross_page(
    pdf_path: str, *, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[dict]:
    """Slide a window across the full document text (pages joined), so paragraphs
    that straddle page boundaries stay in a single chunk. Each chunk records the
    1-based page numbers it spans via a parallel char-to-page mapping."""
    doc = fitz.open(pdf_path)
    try:
        page_texts: list[tuple[int, str]] = []
        for idx in range(doc.page_count):
            cleaned = re.sub(r"\s+", " ", doc[idx].get_text()).strip()
            if cleaned:
                page_texts.append((idx + 1, cleaned))
    finally:
        doc.close()

    if not page_texts:
        return []

    parts: list[str] = []
    char_to_page: list[int] = []
    for page_no, text in page_texts:
        if parts:
            parts.append(" ")
            char_to_page.append(page_no)
        parts.append(text)
        char_to_page.extend([page_no] * len(text))

    full_text = "".join(parts)
    out: list[dict] = []
    i = 0
    while i < len(full_text):
        end = min(i + chunk_chars, len(full_text))
        slice_text = full_text[i:end].strip()
        if slice_text:
            out.append({
                "text": slice_text,
                "page_start": char_to_page[i],
                "page_end": char_to_page[end - 1],
            })
        if end >= len(full_text):
            break
        i = end - overlap
        if i <= 0:
            i = end
    return out


# ---------- embedding ----------


def _hash_embed(text: str, *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Hash-based deterministic fallback embedding. Captures lexical overlap
    but NOT semantics — see file docstring."""
    vec = [0.0] * dim
    if not text:
        return vec

    words = re.findall(r"\w+", text.lower())
    cjk_chars = re.findall(r"[一-鿿]", text)
    bigrams = [
        cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)
    ]
    tokens = words + bigrams + cjk_chars
    if not tokens:
        return vec

    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        vec[bucket] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


async def embed_text(
    api_settings: dict | None, text: str, *, dim: int = EMBEDDING_DIM
) -> list[float]:
    """Embed a single text via the user's configured embedding endpoint.
    Falls back to the local hash-embed when the user has no embedding key
    (offline degradation) or the API errors — retrieval never blocks.
    Issue 19."""
    if not text:
        return [0.0] * dim
    resolved = resolve_embedding(api_settings)
    if resolved is None:
        return _hash_embed(text, dim=dim)
    client, model = resolved
    try:
        resp = await client.embeddings.create(
            model=model,
            input=text,
            dimensions=dim,
        )
        return list(resp.data[0].embedding)
    except Exception:  # noqa: BLE001
        logger.exception("embedding API failed; falling back to hash embed")
        return _hash_embed(text, dim=dim)


async def _batch_embed_texts(
    api_settings: dict | None,
    texts: list[str],
    *,
    dim: int = EMBEDDING_DIM,
) -> list[list[float]]:
    """Embed multiple texts in one API call. Falls back to per-item hash embed."""
    if not texts:
        return []
    resolved = resolve_embedding(api_settings)
    if resolved is None:
        return [_hash_embed(t, dim=dim) for t in texts]
    client, model = resolved
    try:
        resp = await client.embeddings.create(
            model=model,
            input=texts,
            dimensions=dim,
        )
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]
    except Exception:  # noqa: BLE001
        logger.exception("batch embedding API failed; falling back to hash embed")
        return [_hash_embed(t, dim=dim) for t in texts]


# Query-vector cache: MD5(text) → (vector, timestamp). Avoids re-calling the
# embedding API for the same query string within a 5-minute window.
_embed_cache: dict[str, tuple[list[float], float]] = {}
_EMBED_CACHE_TTL = 300


async def _cached_embed(
    api_settings: dict | None, text: str, *, dim: int = EMBEDDING_DIM
) -> list[float]:
    s = api_settings or {}
    # Identity = embedding provider/model so users on different endpoints
    # (or the hash fallback) never share cached query vectors.
    ident = (
        f"{s.get('embedding_base_url', '')}|{s.get('embedding_model', '')}"
        if s.get("embedding_api_key")
        else "hash"
    )
    key = hashlib.md5(f"{ident}|{text}".encode()).hexdigest()
    entry = _embed_cache.get(key)
    if entry is not None and time.monotonic() - entry[1] < _EMBED_CACHE_TTL:
        return entry[0]
    vec = await embed_text(api_settings, text, dim=dim)
    _embed_cache[key] = (vec, time.monotonic())
    return vec


# ---------- bulk index ----------


async def index_course_chunks(
    api_settings: dict | None, course_id: uuid.UUID, pdf_path: str
) -> int:
    """Compute embeddings for all chunks of a course's PDF and insert.
    Returns number of chunks inserted. Idempotent: skips if rows already exist."""
    async with SessionLocal() as db:
        existing_q = await db.execute(
            select(DocumentChunk.id).where(DocumentChunk.course_id == course_id).limit(1)
        )
        if existing_q.first() is not None:
            return 0

        chunks = chunk_pdf_cross_page(pdf_path)
        texts = [c["text"] for c in chunks]
        embeddings = await _batch_embed_texts(api_settings, texts)
        for c, emb in zip(chunks, embeddings):
            db.add(
                DocumentChunk(
                    course_id=course_id,
                    text=c["text"],
                    page_start=c["page_start"],
                    page_end=c["page_end"],
                    embedding=emb,
                )
            )
        await db.commit()
        return len(chunks)


# ---------- retrieval ----------


async def fetch_page_range_chunks(
    course_id: uuid.UUID,
    page_start: int,
    page_end: int,
    db: AsyncSession,
) -> list[DocumentChunk]:
    """Return ALL chunks overlapping the KP page range, in reading order.

    Used instead of cosine top-k when page bounds are known — avoids false
    negatives from similarity thresholding on a small, fully-relevant set.
    No embedding call needed."""
    result = await db.execute(
        select(DocumentChunk)
        .where(
            DocumentChunk.course_id == course_id,
            DocumentChunk.page_start <= page_end,
            DocumentChunk.page_end >= page_start,
        )
        .order_by(DocumentChunk.page_start, DocumentChunk.page_end)
    )
    return list(result.scalars().all())


async def search_top_k(
    api_settings: dict | None,
    course_id: uuid.UUID,
    query: str,
    db: AsyncSession,
    *,
    k: int = 3,
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[DocumentChunk]:
    if not query.strip():
        return []
    q_vec = await _cached_embed(api_settings, query)
    conditions: list = [DocumentChunk.course_id == course_id]
    if page_start is not None and page_end is not None:
        # overlap: chunk must start before KP ends AND end after KP starts
        conditions.append(DocumentChunk.page_start <= page_end)
        conditions.append(DocumentChunk.page_end >= page_start)
    result = await db.execute(
        select(DocumentChunk)
        .where(and_(*conditions))
        .order_by(DocumentChunk.embedding.cosine_distance(q_vec))
        .limit(k)
    )
    return list(result.scalars().all())
