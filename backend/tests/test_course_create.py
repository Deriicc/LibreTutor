"""Course creation: file-type sniffing + EPUB upload. Calls the route
coroutine directly with a real session (project test style). The
background builder is monkeypatched off so no LLM/IO is triggered;
uploaded files + rows are cleaned in finally."""
import io
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete

from app.config import settings
from app.courses import router as courses
from app.courses.router import _ext_of, create_course
from app.db import SessionLocal
from app.models import Course
from tests.epub_fixture import epub_bytes


def _md() -> UploadFile:
    return UploadFile(file=io.BytesIO(b"# t\n\nbody"), filename="x.md")


def _epub() -> UploadFile:
    return UploadFile(file=io.BytesIO(epub_bytes()), filename="book.epub")


def _fake_epub() -> UploadFile:
    return UploadFile(file=io.BytesIO(b"not a zip at all"), filename="book.epub")


async def _cleanup_course(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()
    shutil.rmtree(Path(settings.upload_dir) / str(course_id), ignore_errors=True)


def test_ext_of_recognizes_epub():
    assert _ext_of("Some Book.EPUB") == ".epub"
    assert _ext_of("x.pdf") == ".pdf"
    assert _ext_of("x.txt") == ""


async def test_create_course_accepts_markdown(monkeypatch):
    monkeypatch.setattr(courses, "_spawn_builder", lambda *a, **k: None)
    async with SessionLocal() as db:
        course = await create_course(name="md course", file=_md(), db=db)
        try:
            assert course.id is not None
            assert course.source_pdf_path.endswith(".md")
        finally:
            await _cleanup_course(course.id)


async def test_create_course_accepts_epub(monkeypatch):
    monkeypatch.setattr(courses, "_spawn_builder", lambda *a, **k: None)
    async with SessionLocal() as db:
        course = await create_course(name="epub course", file=_epub(), db=db)
        try:
            assert course.id is not None
            assert course.source_pdf_path.endswith(".epub")
        finally:
            await _cleanup_course(course.id)


async def test_create_course_rejects_fake_epub(monkeypatch):
    monkeypatch.setattr(courses, "_spawn_builder", lambda *a, **k: None)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            await create_course(name="bad", file=_fake_epub(), db=db)
        assert ei.value.status_code == 400
        assert "EPUB" in ei.value.detail
