import asyncio
import io
import json
import logging
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chat.persona_generator import compute_scene_signature, generate_few_shots
from app.chat.socratic import (
    DIALOGUE_TEMPERATURE,
    assemble_system_prompt,
)
from app.config import settings
from app.courses.builder import build_chapter_tree
from app.courses.teacher_persona import default_scene, render_persona
from app.lang import lang_of
from app.courses.schemas import (
    ChapterTreeOut,
    CourseOut,
    TeacherConfigIn,
    TeacherConfigOut,
)
from app.db import get_session
from app.kp.decider import aggregate_status
from app.llm import stream_chat
from app.models import (
    Chapter,
    Course,
    KnowledgePoint,
    KPStatus,
    Section,
    TeacherConfig,
    TeacherDiaryEntry,
)
from app.user_llm import load_api_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courses", tags=["courses"])

PDF_MAGIC = b"%PDF-"
# EPUB is a ZIP container; the ZIP local-file-header signature is the
# cheapest sniff that rejects a non-epub file renamed to .epub. It fits
# within the bytes already read for the PDF check (no extra read).
EPUB_MAGIC = b"PK\x03\x04"
CHUNK_SIZE = 1024 * 1024
ALLOWED_EXTENSIONS = (".pdf", ".epub", ".md", ".markdown")
# Uploaded avatars are normalized (orientation-fixed, downscaled,
# re-encoded) to one format/size so any reasonable image just works.
AVATAR_MAX_DIM = 512
AVATAR_MEDIA_TYPE = "image/webp"


def _ext_of(filename: str) -> str:
    lower = filename.lower()
    for ext in ALLOWED_EXTENSIONS:
        if lower.endswith(ext):
            return ext
    return ""


def _normalize_avatar(raw: bytes) -> bytes:
    """Decode any common image, fix EXIF orientation, downscale to fit
    AVATAR_MAX_DIM (never upscale), re-encode as WEBP. Accepts a wide
    range of inputs/sizes so uploads rarely fail; raises ValueError on
    something that isn't a decodable image."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((AVATAR_MAX_DIM, AVATAR_MAX_DIM))
        img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=82, method=6)
    except Exception as exc:  # noqa: BLE001 — any decode/encode failure = bad image
        raise ValueError(str(exc)) from exc
    return out.getvalue()


def _course_upload_dir(course_id: uuid.UUID) -> Path:
    path = Path(settings.upload_dir) / str(course_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _load_course(course_id: uuid.UUID, db: AsyncSession) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return course


def _spawn_builder(course_id: uuid.UUID, pdf_path: str) -> None:
    """Fire-and-forget background build. Errors are persisted on Course."""

    async def _run() -> None:
        try:
            await build_chapter_tree(course_id, pdf_path)
        except Exception:  # noqa: BLE001
            logger.exception("background build_chapter_tree errored")

    asyncio.create_task(_run())


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(
    name: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> Course:
    filename = file.filename or ""
    ext = _ext_of(filename)
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持 PDF、EPUB 和 Markdown 文件（.pdf / .epub / .md / .markdown）",
        )

    # PDF/EPUB: verify magic bytes. Markdown: just take the first chunk as-is.
    head = await file.read(len(PDF_MAGIC))
    if ext == ".pdf" and head != PDF_MAGIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 文件内容无效（缺少 PDF 文件头）",
        )
    if ext == ".epub" and not head.startswith(EPUB_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="EPUB 文件内容无效（不是有效的 EPUB/ZIP 文件）",
        )

    course_id = uuid.uuid4()
    target_dir = _course_upload_dir(course_id)
    target_path = target_dir / f"source{ext}"

    max_mb = settings.max_pdf_bytes // (1024 * 1024)
    written = len(head)
    try:
        with target_path.open("wb") as out:
            out.write(head)
            while chunk := await file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > settings.max_pdf_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件超过 {max_mb}MB 上限，请压缩后重新上传",
                    )
                out.write(chunk)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise

    course = Course(
        id=course_id,
        name=name.strip(),
        source_pdf_path=str(target_path),
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    _spawn_builder(course.id, str(target_path))
    return course


@router.get("", response_model=list[CourseOut])
async def list_courses(
    db: AsyncSession = Depends(get_session),
) -> list[CourseOut]:
    courses_q = await db.execute(
        select(Course).order_by(Course.created_at.desc())
    )
    courses = list(courses_q.scalars().all())
    if not courses:
        return []

    # Single aggregation query: KP pass counts for all courses at once.
    course_ids = [c.id for c in courses]
    kp_q = await db.execute(
        select(
            Chapter.course_id,
            func.count(KnowledgePoint.id).label("kp_total"),
            func.sum(
                case((KnowledgePoint.status == KPStatus.passed, 1), else_=0)
            ).label("kp_passed"),
        )
        .join(Section, Section.chapter_id == Chapter.id)
        .join(KnowledgePoint, KnowledgePoint.section_id == Section.id)
        .where(Chapter.course_id.in_(course_ids))
        # Synthetic 全书导读/全书总结 KPs are read-only and never pass —
        # excluding them keeps course progress able to reach 100%.
        .where(KnowledgePoint.boundary["kind"].astext.is_(None))
        .group_by(Chapter.course_id)
    )
    kp_by_course = {row.course_id: (int(row.kp_passed), int(row.kp_total)) for row in kp_q.all()}

    result = []
    for c in courses:
        out = CourseOut.model_validate(c)
        out.kp_passed, out.kp_total = kp_by_course.get(c.id, (0, 0))
        result.append(out)
    return result


def _config_to_out(config: TeacherConfig | None, lang: str = "zh") -> TeacherConfigOut:
    if config is None:
        return TeacherConfigOut(
            scene=default_scene(lang),
            learner_context="",
            has_generated_few_shots=False,
            scene_dirty=True,
        )
    has_few_shots = bool((config.generated_few_shots or "").strip())
    expected_sig = compute_scene_signature(config.scene)
    scene_dirty = (config.scene_signature or "") != expected_sig
    return TeacherConfigOut(
        scene=config.scene,
        learner_context=config.learner_context,
        has_generated_few_shots=has_few_shots,
        scene_dirty=scene_dirty,
        has_avatar=bool(config.avatar_path),
    )


async def _regenerate_and_persist(
    config: TeacherConfig, db: AsyncSession, api_settings: dict | None = None
) -> None:
    """Call LLM to regenerate few-shots and persist on the given config row."""
    few_shots = await generate_few_shots(config.scene, api_settings=api_settings)
    config.generated_few_shots = few_shots or None
    config.scene_signature = (
        compute_scene_signature(config.scene) if few_shots else None
    )
    await db.commit()
    await db.refresh(config)


@router.get("/{course_id}/teacher-config", response_model=TeacherConfigOut)
async def get_teacher_config(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> TeacherConfigOut:
    await _load_course(course_id, db)
    config = await db.get(TeacherConfig, course_id)
    lang = lang_of(await load_api_settings(db))
    return _config_to_out(config, lang)


@router.put("/{course_id}/teacher-config", response_model=TeacherConfigOut)
async def put_teacher_config(
    course_id: uuid.UUID,
    payload: TeacherConfigIn,
    db: AsyncSession = Depends(get_session),
) -> TeacherConfigOut:
    await _load_course(course_id, db)
    config = await db.get(TeacherConfig, course_id)
    scene = payload.scene
    learner_context = payload.learner_context
    if config is None:
        config = TeacherConfig(
            course_id=course_id,
            scene=scene,
            learner_context=learner_context,
        )
        db.add(config)
        scene_changed = True
    else:
        scene_changed = config.scene != scene
        config.scene = scene
        config.learner_context = learner_context
        if scene_changed:
            config.generated_few_shots = None
            config.scene_signature = None
    await db.commit()
    await db.refresh(config)
    if scene_changed and scene.strip():
        await _regenerate_and_persist(config, db, await load_api_settings(db))
    return _config_to_out(config)


@router.put(
    "/{course_id}/teacher-config/avatar",
    response_model=TeacherConfigOut,
)
async def put_teacher_avatar(
    course_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> TeacherConfigOut:
    await _load_course(course_id, db)

    raw = b""
    while chunk := await file.read(CHUNK_SIZE):
        raw += chunk
        if len(raw) > settings.max_avatar_bytes:
            max_mb = settings.max_avatar_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"图片超过 {max_mb}MB 上限",
            )

    try:
        webp = _normalize_avatar(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法识别的图片文件，请换一张图片",
        ) from exc

    target_dir = _course_upload_dir(course_id)
    # One canonical name; replacing just overwrites it.
    target_path = target_dir / "avatar.webp"
    target_path.write_bytes(webp)

    config = await db.get(TeacherConfig, course_id)
    if config is None:
        config = TeacherConfig(
            course_id=course_id, avatar_path=str(target_path)
        )
        db.add(config)
    else:
        config.avatar_path = str(target_path)
    await db.commit()
    await db.refresh(config)
    return _config_to_out(config)


@router.get("/{course_id}/teacher-config/avatar")
async def get_teacher_avatar(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> FileResponse:
    await _load_course(course_id, db)
    config = await db.get(TeacherConfig, course_id)
    if config is None or not config.avatar_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未上传头像"
        )
    path = Path(config.avatar_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="头像文件丢失"
        )
    return FileResponse(
        path,
        media_type=AVATAR_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache"},
    )


@router.post(
    "/{course_id}/teacher-config/regenerate-few-shots",
    response_model=TeacherConfigOut,
)
async def regenerate_few_shots_endpoint(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> TeacherConfigOut:
    await _load_course(course_id, db)
    config = await db.get(TeacherConfig, course_id)
    if config is None or not config.scene.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先填写并保存教学场景",
        )
    await _regenerate_and_persist(config, db, await load_api_settings(db))
    return _config_to_out(config)


class TestChatMessageIn(BaseModel):
    role: str
    content: str


class TestChatIn(BaseModel):
    messages: list[TestChatMessageIn]


TEST_CHAT_LAYER3 = {
    "zh": (
        "当前学习上下文：\n"
        "- 测试场景：暂无具体知识点，请按场景人设和学生自由对谈。\n"
        "- 必要时可引入「勾股定理」作为示例话题。\n"
        "- 这是一段试聊，旨在让用户感受 AI 教师的风格。"
    ),
    "en": (
        "Current learning context:\n"
        "- Test scene: no specific knowledge point; chat freely with the student "
        "in the scene persona.\n"
        "- You may bring in the Pythagorean theorem as an example topic if needed.\n"
        "- This is a trial chat to let the user feel the AI teacher's style."
    ),
}


def _sse_bytes(data: str, event: str | None = None) -> bytes:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {data}\n\n".encode("utf-8")


@router.post("/{course_id}/teacher-config/test-chat")
async def test_chat(
    course_id: uuid.UUID,
    payload: TestChatIn,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await _load_course(course_id, db)
    config = await db.get(TeacherConfig, course_id)
    if config is None or not config.scene.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先保存教学场景再来试聊",
        )

    api_settings = await load_api_settings(db)
    lang = lang_of(api_settings)
    layer2 = render_persona(
        config.scene, config.learner_context, config.generated_few_shots, lang
    )
    system_content = assemble_system_prompt(
        layer2, TEST_CHAT_LAYER3[lang], turn_count=0, lang=lang
    )

    llm_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content}
    ]
    llm_messages.extend({"role": m.role, "content": m.content} for m in payload.messages)

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for delta in stream_chat(
                api_settings, llm_messages, temperature=DIALOGUE_TEMPERATURE
            ):
                yield _sse_bytes(json.dumps({"delta": delta}, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            logger.exception("test-chat stream failed for course %s", course_id)
            yield _sse_bytes(
                json.dumps(
                    {"message": "LLM 调用失败，请稍后重试"},
                    ensure_ascii=False,
                ),
                event="error",
            )
            return
        yield _sse_bytes("{}", event="done")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{course_id}/diary")
async def get_course_diary(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The teacher's diary book — chronological, read-only. Replaces the
    old learning-report page (ADR-0023). Pending/failed entries are
    returned too so the book can show a "not written yet" placeholder
    page; the reaper backfills them."""
    course = await _load_course(course_id, db)
    rows = (
        await db.execute(
            select(TeacherDiaryEntry, KnowledgePoint.title)
            .join(
                KnowledgePoint,
                KnowledgePoint.id == TeacherDiaryEntry.kp_id,
            )
            .where(TeacherDiaryEntry.course_id == course_id)
            .order_by(TeacherDiaryEntry.created_at)
        )
    ).all()
    return {
        "course_name": course.name,
        "entries": [
            {
                "kp_id": str(e.kp_id),
                "kp_title": title,
                "attempt": e.attempt,
                "body": e.body,
                "author_signature": e.author_signature,
                "author_label": e.author_label,
                "status": getattr(e.status, "value", e.status),
                "created_at": e.created_at.isoformat()
                if e.created_at
                else None,
            }
            for e, title in rows
        ],
    }


@router.get("/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> Course:
    return await _load_course(course_id, db)


async def _delete_course_record(course: Course, db: AsyncSession) -> None:
    """Delete a course (DB cascade clears every child row) and its on-disk
    artifacts (source file + teacher avatar), which all live under one
    per-course directory."""
    course_id = course.id
    course_dir = Path(settings.upload_dir) / str(course_id)
    await db.delete(course)
    await db.commit()
    try:
        shutil.rmtree(course_dir, ignore_errors=True)
    except OSError:
        logger.exception("failed to remove upload dir for course %s", course_id)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> None:
    course = await _load_course(course_id, db)
    await _delete_course_record(course, db)


@router.get("/{course_id}/chapter-tree", response_model=ChapterTreeOut)
async def get_chapter_tree(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> ChapterTreeOut:
    course = await _load_course(course_id, db)

    result = await db.execute(
        select(Chapter)
        .where(Chapter.course_id == course_id)
        .order_by(Chapter.order_index)
        .options(selectinload(Chapter.sections).selectinload(Section.knowledge_points))
    )
    chapters = list(result.scalars().all())

    # roll up KP statuses → section, then section → chapter
    chapter_payloads = []
    for chapter in chapters:
        section_payloads = []
        for section in chapter.sections:
            # Synthetic 全书导读/全书总结 KPs are read-only — exclude them
            # from rollup so they never pin a chapter to in_progress.
            section_status = aggregate_status(
                [
                    kp.status
                    for kp in section.knowledge_points
                    if not (kp.boundary or {}).get("kind")
                ]
            )
            section_payloads.append(
                {
                    "id": section.id,
                    "title": section.title,
                    "order_index": section.order_index,
                    "status": section_status,
                    "knowledge_points": section.knowledge_points,
                }
            )
        chapter_status = aggregate_status([s["status"] for s in section_payloads])
        chapter_payloads.append(
            {
                "id": chapter.id,
                "title": chapter.title,
                "order_index": chapter.order_index,
                "status": chapter_status,
                "sections": section_payloads,
            }
        )

    return ChapterTreeOut.model_validate(
        {
            "course_id": course_id,
            "generation_status": course.generation_status,
            "generation_error": course.generation_error,
            "chapters": chapter_payloads,
        },
        from_attributes=True,
    )
