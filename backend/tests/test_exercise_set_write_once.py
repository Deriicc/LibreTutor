"""Concurrency regression: the exercise set is write-once per (kp_id, attempt).

Reproduces the bug where duplicate assessment runs (StrictMode double-fire +
nondeterministic LLM count) spawn several tailors that race on the same row.
With an overwriting upsert a *late* writer swapped the questions/size out from
under a page that had already rendered an earlier writer's set, causing the
submit-time `answers count != exercise set size` 422.

The reproduction is temporal: a fast writer returns its set (what the page
renders) and a slow writer commits afterwards. Both pass the early
`existing is None` check, so the conflict resolution decides the outcome —
`do_update` overwrites (bug), `do_nothing` keeps the first writer (fixed).
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete

from app.db import SessionLocal
from app.kp import materializer as materializer_module
from app.kp.materializer import materialize_kp_exercise_set
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPExerciseSet,
    KPMaterial,
    Section,
)


class _FakeEx:
    def __init__(self, i: int) -> None:
        self.i = i

    def model_dump(self, mode: str = "json") -> dict:
        return {"type": "mcq", "question": f"q{self.i}"}


class _FakePayload:
    def __init__(self, n: int) -> None:
        self.exercises = [_FakeEx(i) for i in range(n)]


async def _setup_kp() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="write-once test",
            source_pdf_path="/tmp/wo.pdf",
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
        kp = KnowledgePoint(section_id=sec.id, title="kp", order_index=0, boundary={})
        db.add(kp)
        await db.flush()
        await db.commit()
        return course.id, kp.id


async def test_late_tailor_cannot_overwrite_a_rendered_exercise_set(monkeypatch):
    course_id, kp_id = await _setup_kp()

    # The count=4 writer is fast (it "serves the page"); the count=3 writer is
    # slow and commits afterwards. Both still read `existing is None` first,
    # because both db.get() calls happen before either inserts.
    async def _stub_generate(**kwargs):
        await asyncio.sleep(0.0 if kwargs["count"] == 4 else 0.2)
        return _FakePayload(kwargs["count"])

    monkeypatch.setattr(materializer_module, "generate_exercise_set", _stub_generate)

    material = KPMaterial(kp_id=kp_id, keyphrases=["a", "b", "c"])
    rendered: dict[str, int] = {}

    async def writer(count: int) -> None:
        async with SessionLocal() as db:
            row = await materialize_kp_exercise_set(
                db,
                kp_id=kp_id,
                attempt=1,
                kp_title="kp",
                pdf_path="/tmp/wo.pdf",
                page_start=1,
                page_end=2,
                material=material,
                count=count,
            )
            if count == 4:  # the set the page rendered
                rendered["size"] = len(row.exercises)

    try:
        await asyncio.gather(writer(4), writer(3))

        async with SessionLocal() as db:
            final = await db.get(KPExerciseSet, (kp_id, 1))
            assert final is not None
            db_size = len(final.exercises)

        # The set the student rendered must be exactly the set that persists,
        # so the submit-time size check can never disagree. (Pre-fix, the slow
        # count=3 writer overwrote the rendered count=4 set → 4 != 3.)
        assert rendered["size"] == db_size, (
            f"rendered {rendered['size']} but DB has {db_size}"
        )
        assert final.count == db_size
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
