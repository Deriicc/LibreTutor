"""Course-build prewarm: generates KPMaterial (not exercises) per KP."""
import json
import uuid
from pathlib import Path

import fitz  # type: ignore[import-untyped]
from sqlalchemy import delete, select

from app.courses import builder
from app.db import SessionLocal
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPMaterial,
    Section,
)


def _make_fixture_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((50, 72), f"page {i + 1}: content for prewarm test")
    out = tmp_path / "prewarm.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _valid_material_payload() -> dict:
    return {
        "layer3_prompt": "用极限的视角切入，先让学生说出他理解中的「无限小」",
        "keyphrases": ["极限", "无穷小", "邻域"],
        "knowledge_checklist": [
            {"concept": "极限定义", "description": "ε-δ", "must_anchor": True},
            {"concept": "邻域", "description": "开区间", "must_anchor": True},
            {"concept": "无穷小", "description": "趋于 0 的量", "must_anchor": False},
        ],
    }


async def _setup_course_with_kps(pdf_path: str, n_kps: int = 3) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="prewarm",
            source_pdf_path=pdf_path,
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
        for i in range(n_kps):
            db.add(
                KnowledgePoint(
                    section_id=section.id,
                    title=f"kp{i}",
                    order_index=i,
                    boundary={"page_start": 1, "page_end": 2},
                )
            )
        await db.commit()
        return course.id


async def test_prewarm_materializes_all_kps_and_tolerates_failures(monkeypatch, tmp_path):
    pdf_path = _make_fixture_pdf(tmp_path)
    course_id = await _setup_course_with_kps(str(pdf_path), n_kps=3)
    try:
        call_count = {"n": 0}

        async def stub(_api, _messages):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return "invalid json"
            return json.dumps(_valid_material_payload(), ensure_ascii=False)

        monkeypatch.setattr("app.kp.materializer.complete_json", stub)

        n = await builder.prewarm_kp_materials(course_id)

        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(KPMaterial)
                    .join(KnowledgePoint, KPMaterial.kp_id == KnowledgePoint.id)
                    .join(Section, KnowledgePoint.section_id == Section.id)
                    .join(Chapter, Section.chapter_id == Chapter.id)
                    .where(Chapter.course_id == course_id)
                )
            ).scalars().all()
        # At least one KP succeeded; failures are tolerated.
        assert len(rows) >= 1
        assert n == len(rows)
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_prewarm_skips_kps_with_existing_material(monkeypatch, tmp_path):
    pdf_path = _make_fixture_pdf(tmp_path)
    course_id = await _setup_course_with_kps(str(pdf_path), n_kps=2)
    try:
        async with SessionLocal() as db:
            kps = (
                await db.execute(
                    select(KnowledgePoint)
                    .join(Section, KnowledgePoint.section_id == Section.id)
                    .join(Chapter, Section.chapter_id == Chapter.id)
                    .where(Chapter.course_id == course_id)
                )
            ).scalars().all()
            db.add(
                KPMaterial(
                    kp_id=kps[0].id,
                    layer3_prompt="cached",
                    keyphrases=["cached"],
                    knowledge_checklist=[],
                )
            )
            await db.commit()

        call_count = {"n": 0}

        async def stub(_api, _messages):
            call_count["n"] += 1
            return json.dumps(_valid_material_payload(), ensure_ascii=False)

        monkeypatch.setattr("app.kp.materializer.complete_json", stub)

        await builder.prewarm_kp_materials(course_id)

        # Only 1 LLM call (the not-yet-cached KP)
        assert call_count["n"] == 1

        async with SessionLocal() as db:
            cached = await db.get(KPMaterial, kps[0].id)
            assert cached is not None
            assert cached.layer3_prompt == "cached"  # untouched
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
