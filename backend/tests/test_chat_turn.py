"""End-to-end tests for app.chat.turn.assemble_chat_messages.

No LLM is called — assemble_chat_messages is pure read + prompt-string
assembly. We seed a course / KP / material / (optional) document_chunks
and assert the shape and content of the returned llm_messages list.
"""
import uuid

from sqlalchemy import delete

from app.chat.turn import (
    OPENING_USER_PROMPT,
    _build_retrieval_query,
    _kp_page_range,
    assemble_chat_messages,
)
from app.db import SessionLocal
from app.models import (
    Chapter,
    Course,
    DocumentChunk,
    GenerationStatus,
    KnowledgePoint,
    KPMaterial,
    Message,
    MessageRole,
    Section,
)


CHECKLIST = [
    {"concept": "导数定义", "description": "极限形式", "must_anchor": True},
    {"concept": "切线斜率", "description": "几何意义", "must_anchor": True},
    {"concept": "可导与连续", "description": "蕴含关系", "must_anchor": False},
]


async def _setup_kp(
    *,
    boundary: dict | None = None,
    seed_chunks: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Build user/course/chapter/section/KP + KPMaterial. Optional document_chunks."""
    async with SessionLocal() as db:
        course = Course(
            name="chat turn test",
            source_pdf_path="/tmp/chat_turn.pdf",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()
        chapter = Chapter(course_id=course.id, title="ch", order_index=0)
        db.add(chapter)
        await db.flush()
        section = Section(chapter_id=chapter.id, title="sec", order_index=0)
        db.add(section)
        await db.flush()
        kp = KnowledgePoint(
            section_id=section.id,
            title="导数",
            order_index=0,
            boundary=boundary or {},
        )
        db.add(kp)
        await db.flush()
        db.add(
            KPMaterial(
                kp_id=kp.id,
                layer3_prompt="从瞬时变化率切入。",
                keyphrases=["导数", "极限", "斜率"],
                knowledge_checklist=CHECKLIST,
            )
        )
        if seed_chunks:
            db.add(
                DocumentChunk(
                    course_id=course.id,
                    text="导数是函数的瞬时变化率，几何上是切线斜率。",
                    page_start=1,
                    page_end=1,
                    embedding=[0.0] * 1024,
                )
            )
        await db.commit()
        return course.id, kp.id


async def _cleanup(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()


# ---------- pure helpers ----------


def test_kp_page_range_extracts_valid_bounds():
    assert _kp_page_range({"page_start": 1, "page_end": 3}) == (1, 3)


def test_kp_page_range_returns_none_when_reversed():
    assert _kp_page_range({"page_start": 5, "page_end": 2}) == (None, None)


def test_kp_page_range_returns_none_when_missing():
    assert _kp_page_range({}) == (None, None)
    assert _kp_page_range(None) == (None, None)


def test_kp_page_range_returns_none_on_garbage():
    assert _kp_page_range({"page_start": "x", "page_end": 3}) == (None, None)


def test_build_retrieval_query_anchor_only_for_short_msg():
    q = _build_retrieval_query("嗯", "导数", ["极限", "斜率"])
    assert q == "导数 极限 斜率"


def test_build_retrieval_query_appends_substantive_msg():
    q = _build_retrieval_query(
        "什么是导数的几何意义？", "导数", ["极限", "斜率"]
    )
    assert q == "导数 极限 斜率 什么是导数的几何意义？"


def test_build_retrieval_query_handles_empty_keyphrases():
    q = _build_retrieval_query("some user msg", "导数", [])
    assert q == "导数 some user msg"


# ---------- assemble_chat_messages ----------


async def test_assemble_send_flow_returns_system_plus_history():
    """Regular send: history already contains the user msg; no append."""
    course_id, kp_id = await _setup_kp(
        boundary={"page_start": 1, "page_end": 1}, seed_chunks=True
    )
    try:
        async with SessionLocal() as db:
            # Seed a prior turn + the just-arrived user message
            db.add(Message(kp_id=kp_id, role=MessageRole.assistant, content="老师之前说"))
            db.add(Message(kp_id=kp_id, role=MessageRole.user, content="学生回复 prior"))
            db.add(Message(kp_id=kp_id, role=MessageRole.user, content="刚发的"))
            await db.commit()

        async with SessionLocal() as db:
            from sqlalchemy import select

            kp = await db.get(KnowledgePoint, kp_id)
            history = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.kp_id == kp_id)
                        .order_by(Message.created_at)
                    )
                ).scalars().all()
            )
            messages = await assemble_chat_messages(
                db,
                course_id=course_id,
                kp=kp,
                history=history,
                query_text="刚发的",
            )

        # Shape: [system, assistant, user, user]
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "assistant", "content": "老师之前说"}
        assert messages[-1] == {"role": "user", "content": "刚发的"}

        # System contains domain markers: layer1 keywords + layer3 KP title
        sys = messages[0]["content"]
        assert "苏格拉底" in sys  # Layer 1
        assert "导数" in sys  # Layer 3 KP title
        assert "知识清单" in sys  # checklist injected
        # Retrieval block injected from page-range chunks
        assert "教材原文" in sys
        assert "瞬时变化率" in sys
    finally:
        await _cleanup(course_id)


async def test_assemble_opening_flow_appends_opening_user_prompt():
    """Opening: empty history + synthetic user message at the end."""
    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, kp_id)
            messages = await assemble_chat_messages(
                db,
                course_id=course_id,
                kp=kp,
                history=[],
                query_text="",
                append_user=OPENING_USER_PROMPT,
            )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "user", "content": OPENING_USER_PROMPT}
    finally:
        await _cleanup(course_id)


async def test_assemble_soft_cap_directive_appears_at_threshold():
    """When turn_count hits SOFT_TURN_CAP, system gains the 'ask to advance' directive."""
    from app.chat.socratic import SOFT_TURN_CAP

    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            # Seed SOFT_TURN_CAP user messages
            for i in range(SOFT_TURN_CAP):
                db.add(
                    Message(
                        kp_id=kp_id,
                        role=MessageRole.user,
                        content=f"turn {i}",
                    )
                )
            await db.commit()

        async with SessionLocal() as db:
            from sqlalchemy import select

            kp = await db.get(KnowledgePoint, kp_id)
            history = list(
                (
                    await db.execute(
                        select(Message)
                        .where(Message.kp_id == kp_id)
                        .order_by(Message.created_at)
                    )
                ).scalars().all()
            )
            messages = await assemble_chat_messages(
                db,
                course_id=course_id,
                kp=kp,
                history=history,
                query_text="turn 19",
            )
        sys = messages[0]["content"]
        assert "进作业" in sys
    finally:
        await _cleanup(course_id)


async def test_assemble_uses_page_range_when_boundary_present(monkeypatch):
    """Page-range path skips embedding (no LLM/vector API call)."""
    from app.courses import embedding

    embed_called = {"n": 0}

    async def fail_if_called(*_a, **_kw):
        embed_called["n"] += 1
        raise AssertionError("embedding should not be called when page range is set")

    monkeypatch.setattr(embedding, "_cached_embed", fail_if_called)

    course_id, kp_id = await _setup_kp(
        boundary={"page_start": 1, "page_end": 1}, seed_chunks=True
    )
    try:
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, kp_id)
            messages = await assemble_chat_messages(
                db,
                course_id=course_id,
                kp=kp,
                history=[],
                query_text="anything",
                append_user="hi",
            )
        sys = messages[0]["content"]
        # Chunk text from page 1 is injected verbatim
        assert "瞬时变化率" in sys
        assert embed_called["n"] == 0
    finally:
        await _cleanup(course_id)
