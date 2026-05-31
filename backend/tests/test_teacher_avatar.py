"""Teacher avatar upload/serve against real PG.

Calls the router functions directly (no HTTP client in this suite),
mirroring test_diarist/test_attempts. Uploads are normalized server-side
(orientation-fixed, downscaled, re-encoded to WEBP) so a wide range of
formats/sizes works and storage is one canonical .webp per course.
"""

import io
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import delete

from app.config import settings
from app.courses.router import (
    AVATAR_MAX_DIM,
    get_teacher_avatar,
    put_teacher_avatar,
)
from app.db import SessionLocal
from app.models import Course, GenerationStatus, TeacherConfig


def _img(fmt: str, size: tuple[int, int] = (96, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (180, 90, 60)).save(buf, format=fmt)
    return buf.getvalue()


def _upload(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


async def _setup() -> uuid.UUID:
    async with SessionLocal() as db:
        course = Course(
            name="avatar test",
            source_pdf_path="/tmp/a.pdf",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.commit()
        return course.id


async def _teardown(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()
    shutil.rmtree(Path(settings.upload_dir) / str(course_id), ignore_errors=True)


async def test_large_image_downscaled_to_webp_and_served():
    course_id = await _setup()
    try:
        # A big oversized PNG must come back as a small bounded webp.
        async with SessionLocal() as db:
            out = await put_teacher_avatar(
                course_id,
                _upload(_img("PNG", (2000, 1500)), "huge.png"),
                db=db,
            )
            assert out.has_avatar is True

        async with SessionLocal() as db:
            cfg = await db.get(TeacherConfig, course_id)
            assert cfg is not None and cfg.avatar_path.endswith(".webp")
            p = Path(cfg.avatar_path)
            assert p.is_file()
            with Image.open(p) as stored:
                assert stored.format == "WEBP"
                assert max(stored.size) <= AVATAR_MAX_DIM  # downscaled

            resp = await get_teacher_avatar(course_id, db=db)
            assert Path(resp.path) == p
            assert resp.media_type == "image/webp"
    finally:
        await _teardown(course_id)


async def test_accepts_many_formats_and_replaces_cleanly():
    course_id = await _setup()
    try:
        for fmt, name in [
            ("PNG", "a.png"),
            ("JPEG", "b.jpg"),
            ("GIF", "c.gif"),
            ("BMP", "d.bmp"),
            ("WEBP", "e.webp"),
        ]:
            async with SessionLocal() as db:
                out = await put_teacher_avatar(
                    course_id, _upload(_img(fmt), name), db=db
                )
                assert out.has_avatar is True

        async with SessionLocal() as db:
            cfg = await db.get(TeacherConfig, course_id)
            assert cfg.avatar_path.endswith(".webp")
            # exactly one canonical avatar file on disk for this course
            course_dir = Path(settings.upload_dir) / str(course_id)
            files = list(course_dir.glob("avatar.*"))
            assert files == [Path(cfg.avatar_path)]
    finally:
        await _teardown(course_id)


async def test_rejects_non_image():
    course_id = await _setup()
    try:
        async with SessionLocal() as db:
            with pytest.raises(HTTPException) as exc:
                await put_teacher_avatar(
                    course_id,
                    _upload(b"definitely not an image", "x.png"),
                    db=db,
                )
            assert exc.value.status_code == 400
        async with SessionLocal() as db:
            assert await db.get(TeacherConfig, course_id) is None
    finally:
        await _teardown(course_id)


async def test_get_404_when_no_avatar():
    course_id = await _setup()
    try:
        async with SessionLocal() as db:
            with pytest.raises(HTTPException) as exc:
                await get_teacher_avatar(course_id, db=db)
            assert exc.value.status_code == 404
    finally:
        await _teardown(course_id)
