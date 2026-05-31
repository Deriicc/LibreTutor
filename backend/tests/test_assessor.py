"""Tests for the assessor module — pure helpers + DB upsert + LLM contract."""
import json
import uuid

import pytest

from app.kp import assessor
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KPAssessment,
    KnowledgePoint,
    KPMaterial,
    Message,
    MessageRole,
    Section,
)
from app.db import SessionLocal


# ---------- pure helpers ----------


def _msg(role: MessageRole, content: str) -> Message:
    return Message(
        id=uuid.uuid4(),
        kp_id=uuid.uuid4(),
        role=role,
        content=content,
    )


def test_render_history_block_alternates_speakers():
    out = assessor.render_history_block(
        [
            _msg(MessageRole.assistant, "你对导数知道什么？"),
            _msg(MessageRole.user, "斜率？"),
            _msg(MessageRole.assistant, "$y=|x|$ 在 0 处呢？"),
        ]
    )
    lines = out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("[teacher]:")
    assert lines[1].startswith("[student]:")
    assert lines[2].startswith("[teacher]:")
    assert "导数" in lines[0]
    assert "斜率" in lines[1]


def test_render_history_block_empty():
    assert assessor.render_history_block([]) == ""


def test_render_checklist_for_assessor_marks_must_anchor():
    items = [
        {"concept": "A", "description": "desc-A", "must_anchor": True},
        {"concept": "B", "description": "desc-B", "must_anchor": False},
    ]
    out = assessor.render_checklist_for_assessor(items)
    # Concept names must NOT be prefixed with marker characters — earlier
    # versions used '★ {concept}' which the LLM faithfully copied into its
    # JSON output, breaking strict concept-set matching.
    assert "- A：desc-A" in out
    assert "[必须锚定]" in out
    assert "- B：desc-B" in out
    # The non-anchored line must not carry the anchor tag.
    b_line = next(line for line in out.splitlines() if line.startswith("- B"))
    assert "[必须锚定]" not in b_line


def test_render_checklist_for_assessor_empty():
    assert assessor.render_checklist_for_assessor([]) == ""
    assert assessor.render_checklist_for_assessor(None) == ""


def test_build_assessment_messages_includes_three_sections():
    msgs = assessor.build_assessment_messages(
        kp_title="勾股定理",
        checklist_block="- ★ 勾股定理：直角三角形两直角边平方和等于斜边平方",
        history_block="[student]: ...\n[teacher]: ...",
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    user_content = msgs[1]["content"]
    assert "# 知识点" in user_content
    assert "勾股定理" in user_content
    assert "# 知识清单" in user_content
    assert "★" in user_content
    assert "# 对话历史" in user_content


# ---------- parse_and_validate_payload ----------


def _valid_assessment_json(concepts: list[str]) -> str:
    """Build a payload that puts every concept in 'covered'."""
    return json.dumps(
        {
            "covered": [
                {"concept": c, "evidence": f"对话第 N 轮提到了 {c}"} for c in concepts
            ],
            "partial": [],
            "untouched": [],
            "coverage_ratio": 1.0,
            "mastery_summary": "全部掌握",
            "suggested_difficulty": "normal",
            "suggested_count": 5,
        }
    )


def test_parse_and_validate_payload_happy_path():
    raw = _valid_assessment_json(["A", "B", "C"])
    payload = assessor.parse_and_validate_payload(
        raw, expected_concepts=["A", "B", "C"]
    )
    assert payload.coverage_ratio == 1.0
    assert len(payload.covered) == 3


def test_parse_and_validate_payload_rejects_invalid_json():
    with pytest.raises(ValueError, match="合法 JSON"):
        assessor.parse_and_validate_payload("not json", expected_concepts=[])


def test_parse_and_validate_payload_rejects_missing_concepts():
    raw = _valid_assessment_json(["A", "B"])
    with pytest.raises(ValueError, match="漏掉"):
        assessor.parse_and_validate_payload(
            raw, expected_concepts=["A", "B", "C"]
        )


def test_parse_and_validate_payload_rejects_extra_concepts():
    raw = _valid_assessment_json(["A", "B", "C", "D"])
    with pytest.raises(ValueError, match="清单外概念"):
        assessor.parse_and_validate_payload(
            raw, expected_concepts=["A", "B", "C"]
        )


def test_parse_and_validate_payload_rejects_duplicate_across_buckets():
    data = {
        "covered": [{"concept": "A", "evidence": "e1"}],
        "partial": [{"concept": "A", "evidence": "e2"}],
        "untouched": [{"concept": "B", "reason": "r1"}],
        "coverage_ratio": 0.5,
        "mastery_summary": "ok",
        "suggested_difficulty": "easy",
        "suggested_count": 2,
    }
    with pytest.raises(ValueError, match="重复出现"):
        assessor.parse_and_validate_payload(
            json.dumps(data), expected_concepts=["A", "B"]
        )


def test_parse_and_validate_payload_rejects_bad_difficulty():
    data = {
        "covered": [{"concept": "A", "evidence": "e"}],
        "partial": [],
        "untouched": [],
        "coverage_ratio": 1.0,
        "mastery_summary": "ok",
        "suggested_difficulty": "extreme",  # invalid
        "suggested_count": 5,
    }
    with pytest.raises(ValueError, match="字段不合规"):
        assessor.parse_and_validate_payload(
            json.dumps(data), expected_concepts=["A"]
        )


def test_parse_and_validate_payload_rejects_count_out_of_range():
    data = {
        "covered": [{"concept": "A", "evidence": "e"}],
        "partial": [],
        "untouched": [],
        "coverage_ratio": 1.0,
        "mastery_summary": "ok",
        "suggested_difficulty": "easy",
        "suggested_count": 99,
    }
    with pytest.raises(ValueError, match="字段不合规"):
        assessor.parse_and_validate_payload(
            json.dumps(data), expected_concepts=["A"]
        )


def test_parse_and_validate_payload_coerces_coverage_to_two_decimals():
    data = {
        "covered": [{"concept": "A", "evidence": "e"}],
        "partial": [],
        "untouched": [{"concept": "B", "reason": "r"}],
        "coverage_ratio": 0.5,
        "mastery_summary": "ok",
        "suggested_difficulty": "normal",
        "suggested_count": 3,
    }
    payload = assessor.parse_and_validate_payload(
        json.dumps(data), expected_concepts=["A", "B"]
    )
    assert payload.coverage_ratio == 0.5


# ---------- DB-backed run_assessment ----------


async def _setup_kp_with_content_and_history(
    *,
    must_anchor_count: int = 2,
    history: list[tuple[MessageRole, str]],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Build a course / chapter / section / KP, attach kp_content with a
    knowledge_checklist of length 3, and feed in history rows. Returns
    (course_id, kp_id)."""
    async with SessionLocal() as db:
        course = Course(
            name="assessor test",
            source_pdf_path="/tmp/x.pdf",
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
            section_id=section.id, title="导数", order_index=0, boundary={}
        )
        db.add(kp)
        await db.flush()

        checklist = [
            {
                "concept": "导数定义",
                "description": "极限形式",
                "must_anchor": True,
            },
            {
                "concept": "切线斜率",
                "description": "几何意义",
                "must_anchor": True,
            },
            {
                "concept": "可导与连续",
                "description": "蕴含关系",
                "must_anchor": False,
            },
        ]
        # Optionally trim must_anchor count by flipping flags
        if must_anchor_count != 2:
            for i in range(len(checklist)):
                checklist[i]["must_anchor"] = i < must_anchor_count

        db.add(
            KPMaterial(
                kp_id=kp.id,
                layer3_prompt="x" * 12,
                keyphrases=["k1", "k2", "k3"],
                knowledge_checklist=checklist,
            )
        )
        for role, content in history:
            db.add(Message(kp_id=kp.id, role=role, content=content))
        await db.commit()
        return course.id, kp.id


async def test_run_assessment_uses_active_session(monkeypatch):
    """Run with a real session and verify the row is written correctly."""
    course_id, kp_id = await _setup_kp_with_content_and_history(
        history=[
            (MessageRole.assistant, "你对导数知道什么？"),
            (MessageRole.user, "好像跟斜率有关"),
        ],
    )

    captured_user_msg = {"text": ""}

    async def stub(_api, messages):
        captured_user_msg["text"] = messages[1]["content"]
        return json.dumps(
            {
                "covered": [],
                "partial": [
                    {"concept": "切线斜率", "evidence": "提到斜率"}
                ],
                "untouched": [
                    {"concept": "导数定义", "reason": "未提"},
                    {"concept": "可导与连续", "reason": "未提"},
                ],
                "coverage_ratio": 0.17,
                "mastery_summary": "几乎未触及核心",
                "suggested_difficulty": "easy",
                "suggested_count": 2,
            }
        )

    monkeypatch.setattr(assessor, "complete_json", stub)

    async with SessionLocal() as db:
        row = await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert row.kp_id == kp_id
        assert row.attempt == 1
        assert float(row.coverage_ratio) == 0.17
        assert row.suggested_difficulty == "easy"
        assert row.suggested_count == 2
        assert len(row.partial) == 1
        assert row.partial[0]["concept"] == "切线斜率"

    # Sanity: prompt actually contained our pieces.
    assert "导数" in captured_user_msg["text"]
    assert "[必须锚定]" in captured_user_msg["text"]


async def test_run_assessment_upserts_on_same_attempt(monkeypatch):
    """Running assessment twice on the same (kp_id, attempt) should
    overwrite the row, not crash on duplicate primary key."""
    course_id, kp_id = await _setup_kp_with_content_and_history(
        history=[
            (MessageRole.assistant, "q1"),
            (MessageRole.user, "a1"),
        ],
    )

    call = {"n": 0}

    async def stub(_api, _messages):
        call["n"] += 1
        diff = "easy" if call["n"] == 1 else "normal"
        return json.dumps(
            {
                "covered": [{"concept": "切线斜率", "evidence": "e"}],
                "partial": [],
                "untouched": [
                    {"concept": "导数定义", "reason": "r"},
                    {"concept": "可导与连续", "reason": "r"},
                ],
                "coverage_ratio": 0.33,
                "mastery_summary": f"summary v{call['n']}",
                "suggested_difficulty": diff,
                "suggested_count": 2 + call["n"],
            }
        )

    monkeypatch.setattr(assessor, "complete_json", stub)

    async with SessionLocal() as db:
        await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
        # Second run with different LLM output should overwrite, not duplicate
        row2 = await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert row2.suggested_difficulty == "normal"
        assert row2.suggested_count == 4
        assert "v2" in row2.mastery_summary


async def test_run_assessment_falls_back_when_no_checklist(monkeypatch):
    """KP without knowledge_checklist (no KP_content row at all) →
    empty fallback, no LLM call."""
    async with SessionLocal() as db:
        course = Course(
            name="x",
            source_pdf_path="/tmp/x.pdf",
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
            section_id=section.id, title="x", order_index=0, boundary={}
        )
        db.add(kp)
        await db.flush()
        # Note: NO KPMaterial row — so checklist is implicitly empty.
        db.add(
            Message(kp_id=kp.id, role=MessageRole.user, content="hi")
        )
        await db.commit()
        kp_id = kp.id

    called = {"n": 0}

    async def stub(_api, _messages):
        called["n"] += 1
        return "should not be called"

    monkeypatch.setattr(assessor, "complete_json", stub)

    async with SessionLocal() as db:
        row = await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert called["n"] == 0
        assert float(row.coverage_ratio) == 0.0
        assert row.suggested_count == 2
        assert row.suggested_difficulty == "easy"
        assert row.covered == []


async def test_run_assessment_falls_back_when_no_history(monkeypatch):
    """Brand-new KP with checklist but zero messages → empty fallback."""
    course_id, kp_id = await _setup_kp_with_content_and_history(history=[])

    called = {"n": 0}

    async def stub(_api, _messages):
        called["n"] += 1
        return "should not be called"

    monkeypatch.setattr(assessor, "complete_json", stub)

    async with SessionLocal() as db:
        row = await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert called["n"] == 0
        assert float(row.coverage_ratio) == 0.0


async def test_run_assessment_propagates_validation_failure(monkeypatch):
    course_id, kp_id = await _setup_kp_with_content_and_history(
        history=[
            (MessageRole.assistant, "q"),
            (MessageRole.user, "a"),
        ],
    )

    async def stub(_api, _messages):
        # Missing one concept from the checklist
        return json.dumps(
            {
                "covered": [{"concept": "切线斜率", "evidence": "e"}],
                "partial": [],
                "untouched": [],
                "coverage_ratio": 1.0,
                "mastery_summary": "ok",
                "suggested_difficulty": "normal",
                "suggested_count": 5,
            }
        )

    monkeypatch.setattr(assessor, "complete_json", stub)

    async with SessionLocal() as db:
        with pytest.raises(ValueError, match="漏掉"):
            await assessor.run_assessment(kp_id=kp_id, attempt=1, db=db)
