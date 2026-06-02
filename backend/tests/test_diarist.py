"""Teacher diary: pure render helpers + end-to-end generation /
immutability against real PG (single integration test to avoid
asyncpg loop reuse under pytest-asyncio function-scoped fixtures)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.db import SessionLocal
from app.kp import diarist
from app.kp.router import _attempt_has_activity
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    Message,
    MessageRole,
    Section,
    TeacherConfig,
    TeacherDiaryEntry,
)


# ---------- pure helpers ----------


def _entry(label: str, body: str, *, days_ago: int) -> TeacherDiaryEntry:
    e = TeacherDiaryEntry(
        kp_id=uuid.uuid4(),
        attempt=1,
        course_id=uuid.uuid4(),
        body=body,
        author_signature=f"——{label}",
        author_label=label,
        status="done",
    )
    e.created_at = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return e


def test_render_prior_diary_block_empty_is_first_entry():
    out = diarist.render_prior_diary_block([], char_budget=1000)
    assert "第一篇" in out


def test_render_prior_diary_block_budget_drops_oldest_keeps_chrono():
    old = _entry("三月七", "X" * 400, days_ago=10)
    mid = _entry("三月七", "Y" * 400, days_ago=5)
    new = _entry("费曼", "Z" * 400, days_ago=1)
    # budget fits ~2 of the 3 (each ~ 400 + signature)
    out = diarist.render_prior_diary_block(
        [old, mid, new], char_budget=900
    )
    assert "X" * 400 not in out  # oldest dropped first
    assert "Z" * 400 in out  # newest kept
    # chronological order in the rendered prompt (mid before new)
    assert out.index("Y" * 400) < out.index("Z" * 400)
    assert "费曼" in out  # signatures/labels carried for cross-author memory


def test_parse_diary_payload_valid():
    raw = json.dumps(
        {
            "body": "今天他终于开窍了。",
            "author_signature": "——祥子，深夜",
            "author_label": "丰川祥子",
        }
    )
    p = diarist.parse_diary_payload(raw)
    assert p.author_label == "丰川祥子"


def test_parse_diary_payload_rejects_bad_json():
    with pytest.raises(ValueError, match="不是合法 JSON"):
        diarist.parse_diary_payload("not json")


def test_parse_diary_payload_rejects_missing_field():
    raw = json.dumps({"body": "x", "author_label": "y"})  # no signature
    with pytest.raises(ValueError, match="字段不合规"):
        diarist.parse_diary_payload(raw)


def test_render_facts_block_surfaces_real_facts():
    block = diarist.render_facts_block(
        kp_title="导数",
        attempt=2,
        ended_by="retry",
        kp_passed=False,
        assessment=None,
        grades=[],
        weaknesses=[],
        progress={
            "kp_passed": 3,
            "kp_total": 10,
            "chapter_passed": 1,
            "chapter_total": 4,
            "study_minutes": 42,
        },
    )
    assert "导数" in block
    assert "第 2 次" in block
    assert "重做" in block
    assert "3/10" in block and "42 分钟" in block


def test_render_helpers_localized_to_english():
    block = diarist.render_facts_block(
        kp_title="Derivatives",
        attempt=2,
        ended_by="retry",
        kp_passed=False,
        assessment=None,
        grades=[],
        weaknesses=[],
        progress={
            "kp_passed": 3,
            "kp_total": 10,
            "chapter_passed": 1,
            "chapter_total": 4,
            "study_minutes": 42,
        },
        lang="en",
    )
    assert "Knowledge point: Derivatives" in block
    assert "Teaching this section for time #2" in block
    assert "redid it" in block
    assert "3/10 knowledge points" in block and "42 minutes" in block
    # no Chinese leaked into the English body
    assert not any("一" <= ch <= "鿿" for ch in block)

    from app.models import Message, MessageRole

    hist = diarist.render_history_block(
        [Message(kp_id=uuid.uuid4(), role=MessageRole.user, content="hello")],
        "en",
    )
    assert "[Student] hello" in hist
    assert diarist.render_prior_diary_block([], char_budget=1000, lang="en") == (
        "(This is the first entry in this diary.)"
    )


# ---------- integration: real PG ----------


async def _setup_kp(with_message: bool) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="日记测试课",
            source_pdf_path="/tmp/d.pdf",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()
        ch = Chapter(course_id=course.id, title="ch", order_index=0)
        db.add(ch)
        await db.flush()
        sec = Section(chapter_id=ch.id, title="sec", order_index=0)
        db.add(sec)
        await db.flush()
        kp = KnowledgePoint(
            section_id=sec.id, title="极限", order_index=0, boundary={}
        )
        db.add(kp)
        await db.flush()
        db.add(
            TeacherConfig(
                course_id=course.id,
                scene="你叫小七，温柔耐心。",
                learner_context="无",
            )
        )
        if with_message:
            db.add(
                Message(
                    kp_id=kp.id,
                    role=MessageRole.user,
                    content="老师我不懂极限",
                )
            )
            db.add(
                Message(
                    kp_id=kp.id,
                    role=MessageRole.assistant,
                    content="我们慢慢来。",
                )
            )
        await db.commit()
        return course.id, kp.id


async def test_diary_end_to_end_activity_guard_and_immutable(monkeypatch):
    course_id, kp_id = await _setup_kp(with_message=True)
    try:
        # activity guard: KP has messages → active
        async with SessionLocal() as db:
            assert await _attempt_has_activity(kp_id, 1, db) is True

        calls = {"n": 0}

        async def stub(_api, _messages):
            calls["n"] += 1
            return json.dumps(
                {
                    "body": "今天他第一次主动发问，我很欣慰。",
                    "author_signature": "——小七",
                    "author_label": "小七",
                }
            )

        monkeypatch.setattr(diarist, "complete_json", stub)

        await diarist.generate_diary_entry(
            kp_id, 1, course_id, ended_by="next"
        )

        async with SessionLocal() as db:
            row = await db.get(TeacherDiaryEntry, (kp_id, 1))
            assert row is not None
            assert row.status == "done"
            assert "欣慰" in (row.body or "")
            assert row.author_label == "小七"
            assert row.ended_by == "next"
            assert row.completed_at is not None

        # immutable: re-running does NOT call the LLM again or change body
        await diarist.generate_diary_entry(
            kp_id, 1, course_id, ended_by="retry"
        )
        assert calls["n"] == 1  # short-circuited on done row
        async with SessionLocal() as db:
            row = await db.get(TeacherDiaryEntry, (kp_id, 1))
            assert "欣慰" in (row.body or "")
            assert row.ended_by == "next"  # unchanged
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_attempt_has_activity_false_when_no_message_no_submission():
    course_id, kp_id = await _setup_kp(with_message=False)
    try:
        async with SessionLocal() as db:
            assert await _attempt_has_activity(kp_id, 1, db) is False
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
