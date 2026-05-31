"""Book-level 全书导读/全书总结 material: synthesized from the whole-book
outline + front/back-matter text, never from a KP page slice.

Generator is pure (no DB, LLM stubbed); prewarm routing is real-PG.
"""

import json
import uuid
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest
from sqlalchemy import delete, select

from fastapi import HTTPException

from app.db import SessionLocal
from app.kp import materializer, prewarm
from app.kp.exercise_validators import KPMaterialPayload
from app.courses.router import get_chapter_tree, list_courses
from app.kp.router import (
    advance,
    post_assessment,
    post_exercise_set,
    submit_answers,
)
from app.kp.schemas import AdvanceIn, AnswerIn, SubmitIn
from app.models import KPStatus
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPMaterial,
    Section,
)


def _valid_material_json() -> str:
    return json.dumps(
        {
            "layer3_prompt": "先带学生鸟瞰全书主线，再问他最想先攻哪一章",
            "keyphrases": ["全书主线", "知识地图", "学习路径"],
            "knowledge_checklist": [
                {"concept": "总分总结构", "description": "导读—正文—总结", "must_anchor": True},
                {"concept": "章节脉络", "description": "各章如何串联", "must_anchor": True},
                {"concept": "阅读建议", "description": "怎么读最高效", "must_anchor": False},
            ],
        },
        ensure_ascii=False,
    )


async def test_generate_book_overview_feeds_outline_and_matter_not_page_slice(
    monkeypatch,
):
    seen: dict[str, str] = {}

    async def stub(_api, messages):
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[-1]["content"]
        return _valid_material_json()

    monkeypatch.setattr(materializer, "complete_json", stub)

    payload = await materializer.generate_book_overview_material(
        kind="overview",
        outline_text="第一章 基础\n  1.1 概念\n第二章 进阶\n  2.1 深化",
        matter_text="本书写给初学者，建议按章顺序阅读。",
    )

    # The synthesis input carries the whole-book outline + matter text,
    # and is explicitly a 导读 (overview) task — not a page-slice prompt.
    assert "第一章 基础" in seen["user"]
    assert "2.1 深化" in seen["user"]
    assert "本书写给初学者" in seen["user"]
    assert "导读" in seen["system"] or "导读" in seen["user"]
    assert "PDF 页码" not in seen["user"]

    assert payload.layer3_prompt
    assert 3 <= len(payload.keyphrases) <= 5
    assert sum(1 for c in payload.knowledge_checklist if c.must_anchor) >= 2


def _payload_obj() -> KPMaterialPayload:
    return KPMaterialPayload.model_validate(json.loads(_valid_material_json()))


def _make_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page()
        page.insert_text((50, 72), f"page {i + 1}: real source text content")
    out = tmp_path / "book.pdf"
    doc.save(str(out))
    doc.close()
    return out


async def _seed_tree(pdf_path: str) -> tuple[uuid.UUID, uuid.UUID, dict]:
    """Overview + one body chapter (2 KPs) + summary, persisted directly."""
    ids: dict = {}
    async with SessionLocal() as db:
        course = Course(
            name="bookov",
            source_pdf_path=pdf_path,
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()

        def _ch(title, idx):
            c = Chapter(course_id=course.id, title=title, order_index=idx)
            db.add(c)
            return c

        ov, body, summ = _ch("全书导读", 0), _ch("第一章 基础", 1), _ch("全书总结", 2)
        await db.flush()
        ov_s = Section(chapter_id=ov.id, title="全书导读", order_index=0)
        body_s = Section(chapter_id=body.id, title="1.1 概念", order_index=0)
        summ_s = Section(chapter_id=summ.id, title="全书总结", order_index=0)
        db.add_all([ov_s, body_s, summ_s])
        await db.flush()

        ov_kp = KnowledgePoint(
            section_id=ov_s.id, title="全书导读", order_index=0,
            boundary={"kind": "overview", "matter_pages": [[1, 2]]},
        )
        b1 = KnowledgePoint(
            section_id=body_s.id, title="极限的概念", order_index=0,
            boundary={"page_start": 3, "page_end": 4, "description": "讲极限"},
        )
        b2 = KnowledgePoint(
            section_id=body_s.id, title="连续性", order_index=1,
            boundary={"page_start": 4, "page_end": 5, "description": "讲连续"},
        )
        summ_kp = KnowledgePoint(
            section_id=summ_s.id, title="全书总结", order_index=0,
            boundary={"kind": "summary", "matter_pages": [[5, 6]]},
        )
        db.add_all([ov_kp, b1, b2, summ_kp])
        await db.commit()
        ids = {
            "course": course.id,
            "ov": ov_kp.id, "b1": b1.id, "b2": b2.id, "summ": summ_kp.id,
        }
    return ids["course"], ids


async def test_prewarm_routes_synthetic_kps_to_book_overview_generator(
    tmp_path, monkeypatch
):
    pdf = _make_pdf(tmp_path)
    course_id, ids = await _seed_tree(str(pdf))
    try:
        page_calls: list[str] = []
        book_calls: list[dict] = []

        async def fake_page_gen(kp_title, pdf_path, page_start, page_end, **kw):
            page_calls.append(kp_title)
            return _payload_obj()

        async def fake_book_gen(*, kind, outline_text, matter_text, **kw):
            book_calls.append(
                {"kind": kind, "outline": outline_text, "matter": matter_text}
            )
            return _payload_obj()

        monkeypatch.setattr(materializer, "generate_kp_material", fake_page_gen)
        monkeypatch.setattr(
            materializer, "generate_book_overview_material", fake_book_gen
        )

        await prewarm.prewarm_kp_materials(course_id)

        # Every KP — body and synthetic — ends up with a material row.
        async with SessionLocal() as db:
            for key in ("ov", "b1", "b2", "summ"):
                assert await db.get(KPMaterial, ids[key]) is not None

        # Boundary-page generator ran only for body KPs.
        assert sorted(page_calls) == ["极限的概念", "连续性"]

        # Book-level generator ran for both synthetic KPs, fed the body
        # outline + the matter text extracted from the source.
        assert {c["kind"] for c in book_calls} == {"overview", "summary"}
        for c in book_calls:
            assert "第一章 基础" in c["outline"]
            assert "极限的概念" in c["outline"]
            assert "全书导读" not in c["outline"]  # synthetic excluded
            assert c["matter"].strip()
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_synthetic_kp_cannot_be_advanced_to_passed(tmp_path):
    pdf = _make_pdf(tmp_path)
    course_id, ids = await _seed_tree(str(pdf))
    try:
        async with SessionLocal() as db:
            with pytest.raises(HTTPException) as exc:
                await advance(
                    course_id,
                    ids["ov"],
                    AdvanceIn(action="next"),
                    db=db,
                )
            assert exc.value.status_code == 409
        # Status never flipped to passed.
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, ids["ov"])
            assert kp.status.value != "passed"
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_synthetic_kp_rejects_assessment_and_exercise_loop(tmp_path):
    pdf = _make_pdf(tmp_path)
    course_id, ids = await _seed_tree(str(pdf))
    submit = SubmitIn(
        answers=[AnswerIn(index=0, answer="a"), AnswerIn(index=1, answer="b")]
    )
    try:
        async with SessionLocal() as db:
            for call in (
                post_assessment(course_id, ids["summ"], db=db),
                post_exercise_set(course_id, ids["summ"], db=db),
                submit_answers(
                    course_id, ids["summ"], submit, db=db
                ),
            ):
                with pytest.raises(HTTPException) as exc:
                    await call
                assert exc.value.status_code == 409
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_course_progress_excludes_synthetic_kps(tmp_path):
    pdf = _make_pdf(tmp_path)
    course_id, ids = await _seed_tree(str(pdf))
    try:
        # Both body KPs passed; synthetic KPs left in_progress.
        async with SessionLocal() as db:
            for key in ("b1", "b2"):
                kp = await db.get(KnowledgePoint, ids[key])
                kp.status = KPStatus.passed
            for key in ("ov", "summ"):
                kp = await db.get(KnowledgePoint, ids[key])
                kp.status = KPStatus.in_progress
            await db.commit()

        async with SessionLocal() as db:
            courses = await list_courses(db=db)
        out = next(c for c in courses if c.id == course_id)
        # Synthetic KPs must not inflate the denominator → 2/2, not 2/4.
        assert (out.kp_passed, out.kp_total) == (2, 2)
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_chapter_tree_rollup_ignores_synthetic_kp_status(tmp_path):
    pdf = _make_pdf(tmp_path)
    course_id, ids = await _seed_tree(str(pdf))
    try:
        async with SessionLocal() as db:
            for key in ("b1", "b2"):
                kp = await db.get(KnowledgePoint, ids[key])
                kp.status = KPStatus.passed
            # Synthetic KP in_progress must NOT make its chapter in_progress.
            kp = await db.get(KnowledgePoint, ids["ov"])
            kp.status = KPStatus.in_progress
            await db.commit()

        async with SessionLocal() as db:
            tree = await get_chapter_tree(course_id, db=db)

        by_title = {c.title: c for c in tree.chapters}
        # Body chapter rolls up purely from its real KPs.
        assert by_title["第一章 基础"].status == KPStatus.passed.value
        # Synthetic chapter is neutral (not in_progress) despite its KP.
        assert by_title["全书导读"].status == KPStatus.untouched.value
        # Synthetic KP is still present in the payload for rendering.
        ov_chapter = by_title["全书导读"]
        ov_kps = ov_chapter.sections[0].knowledge_points
        assert len(ov_kps) == 1
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
