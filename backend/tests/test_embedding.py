import math
import uuid
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest
from sqlalchemy import delete

from app.courses import embedding
from app.db import SessionLocal
from app.models import (
    Course,
    DocumentChunk,
    GenerationStatus,
)


# ---------- chunking ----------


def _make_pdf(tmp_path: Path, pages: list[str]) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=10)
    out = tmp_path / "chunk_fixture.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_chunk_pdf_by_chars_emits_chunks_for_each_page(tmp_path):
    pdf = _make_pdf(
        tmp_path,
        [
            "Page one talks about addition and the commutative property.",
            "Page two covers subtraction and how borrowing works.",
        ],
    )
    chunks = embedding.chunk_pdf_by_chars(str(pdf), chunk_chars=200, overlap=20)
    assert len(chunks) >= 2
    assert any("addition" in c["text"] for c in chunks)
    assert any("subtraction" in c["text"] for c in chunks)
    for c in chunks:
        assert c["page_start"] == c["page_end"]
        assert 1 <= c["page_start"] <= 2


def test_chunk_pdf_by_chars_handles_long_page_with_overlap(tmp_path):
    # PDF only renders text that fits inside the page; with default fontsize
    # ~110 chars fit. We pick a chunk_chars small enough that the rendered
    # text spans multiple chunks.
    long_text = "ABCDEFGHIJ " * 30
    pdf = _make_pdf(tmp_path, [long_text])
    chunks = embedding.chunk_pdf_by_chars(str(pdf), chunk_chars=40, overlap=10)
    assert len(chunks) >= 3
    assert all(c["page_start"] == 1 for c in chunks)


def test_chunk_pdf_skips_empty_pages(tmp_path):
    pdf = _make_pdf(tmp_path, ["", "real content here"])
    chunks = embedding.chunk_pdf_by_chars(str(pdf))
    assert all(c["text"].strip() for c in chunks)
    assert any("real content" in c["text"] for c in chunks)


# ---------- embedding ----------


def test_hash_embed_returns_correct_dim_unit_vector():
    v = embedding._hash_embed("hello 加法 交换律")
    assert len(v) == embedding.EMBEDDING_DIM
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-6


def test_hash_embed_is_deterministic():
    a = embedding._hash_embed("the same text")
    b = embedding._hash_embed("the same text")
    assert a == b


def test_hash_embed_distinguishes_different_inputs():
    a = embedding._hash_embed("加法的定义和性质")
    b = embedding._hash_embed("减法的定义和性质")
    assert a != b
    dot = sum(x * y for x, y in zip(a, b))
    assert dot < 1.0


def test_hash_embed_handles_empty_string():
    v = embedding._hash_embed("")
    assert len(v) == embedding.EMBEDDING_DIM
    assert all(x == 0 for x in v)


_WITH_KEY = {
    "embedding_api_key": "fake-key",
    "embedding_model": "fake-model",
}


async def test_embed_text_falls_back_to_hash_when_no_api_key():
    # No embedding_api_key → resolve_embedding returns None → hash embed.
    v = await embedding.embed_text({}, "加法 的 定义")
    expected = embedding._hash_embed("加法 的 定义")
    assert v == expected


async def test_embed_text_uses_api_when_key_set(monkeypatch):
    captured: dict = {}

    class _FakeData:
        def __init__(self, vec):
            self.embedding = vec

    class _FakeResp:
        def __init__(self, vec):
            self.data = [_FakeData(vec)]

    async def fake_create(*, model, input, dimensions):
        captured["model"] = model
        captured["input"] = input
        captured["dimensions"] = dimensions
        return _FakeResp([0.5] * dimensions)

    class _FakeEmbeds:
        create = staticmethod(fake_create)

    class _FakeClient:
        embeddings = _FakeEmbeds()

    monkeypatch.setattr(
        embedding, "resolve_embedding", lambda _s: (_FakeClient(), "fake-model")
    )

    v = await embedding.embed_text(_WITH_KEY, "query")
    assert captured["dimensions"] == embedding.EMBEDDING_DIM
    assert captured["input"] == "query"
    assert v == [0.5] * embedding.EMBEDDING_DIM


async def test_embed_text_falls_back_when_api_raises(monkeypatch):
    async def raising_create(**_kwargs):
        raise RuntimeError("upstream down")

    class _FakeEmbeds:
        create = staticmethod(raising_create)

    class _FakeClient:
        embeddings = _FakeEmbeds()

    monkeypatch.setattr(
        embedding, "resolve_embedding", lambda _s: (_FakeClient(), "fake-model")
    )

    v = await embedding.embed_text(_WITH_KEY, "加法")
    assert v == embedding._hash_embed("加法")


# ---------- integration: index + search against real PG ----------


async def _setup_indexed_course(tmp_path: Path) -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    pdf = _make_pdf(
        tmp_path,
        [
            "Chapter one covers prime numbers. A prime number is divisible only by 1 and itself.",
            "Chapter two teaches the Pythagorean theorem: a squared plus b squared equals c squared.",
            "Chapter three on algebra: solving linear equations with one variable.",
        ],
    )
    async with SessionLocal() as db:
        course = Course(
            name="vec test",
            source_pdf_path=str(pdf),
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()
        course_id = course.id
        await db.commit()
    n = await embedding.index_course_chunks({}, course_id, str(pdf))
    assert n > 0
    return course_id


async def _cleanup_course(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()


async def test_index_and_search_end_to_end(tmp_path):
    course_id = await _setup_indexed_course(tmp_path)
    try:
        async with SessionLocal() as db:
            from sqlalchemy import select

            count_q = await db.execute(
                select(DocumentChunk.id).where(DocumentChunk.course_id == course_id)
            )
            chunks = list(count_q.all())
            assert len(chunks) > 0

            # query for "Pythagorean theorem" should rank chapter 2's chunk highest
            results = await embedding.search_top_k({}, course_id, "Pythagorean theorem squared", db, k=3)
            assert len(results) <= 3
            assert len(results) > 0
            top_text = results[0].text.lower()
            assert "pythagorean" in top_text or "squared" in top_text

            # Empty query yields nothing
            empty = await embedding.search_top_k({}, course_id, "   ", db, k=3)
            assert empty == []

        # Re-running index_course_chunks should be a noop (idempotent on existing rows)
        async with SessionLocal() as db:
            from sqlalchemy import select

            count_before_q = await db.execute(
                select(DocumentChunk.id).where(DocumentChunk.course_id == course_id)
            )
            before = len(list(count_before_q.all()))
        n2 = await embedding.index_course_chunks({}, course_id, "/tmp/whatever.pdf")
        assert n2 == 0  # skipped
        async with SessionLocal() as db:
            from sqlalchemy import select

            count_after_q = await db.execute(
                select(DocumentChunk.id).where(DocumentChunk.course_id == course_id)
            )
            after = len(list(count_after_q.all()))
        assert before == after
    finally:
        await _cleanup_course(course_id)
