import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schemas import MessageOut, SendMessageIn
from app.chat.socratic import DIALOGUE_TEMPERATURE
from app.chat.turn import OPENING_USER_PROMPTS, assemble_chat_messages
from app.lang import lang_of
from app.db import SessionLocal, get_session
from app.llm import stream_chat
from app.models import (
    Chapter,
    Course,
    KnowledgePoint,
    KPStatus,
    Message,
    MessageRole,
    Section,
)
from app.user_llm import load_api_settings

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/courses/{course_id}/kp/{kp_id}/messages",
    tags=["chat"],
)


async def _load_kp(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession,
) -> KnowledgePoint:
    result = await db.execute(
        select(KnowledgePoint)
        .join(Section, KnowledgePoint.section_id == Section.id)
        .join(Chapter, Section.chapter_id == Chapter.id)
        .join(Course, Chapter.course_id == Course.id)
        .where(
            KnowledgePoint.id == kp_id,
            Course.id == course_id,
        )
    )
    kp = result.scalar_one_or_none()
    if kp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="knowledge point not found",
        )
    return kp


def _sse(data: str, event: str | None = None) -> bytes:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {data}\n\n".encode("utf-8")


def _stream_assistant_response(
    kp_id: uuid.UUID,
    attempt: int,
    api_settings: dict | None,
    llm_messages: list[dict[str, str]],
) -> AsyncIterator[bytes]:
    """Drive the LLM stream, persist assistant message on success, emit SSE.

    `attempt` is captured by the caller at request time (not re-read from
    the KP here): the assistant row is written in a fresh session after
    the stream ends, by which point a concurrent retry may have bumped
    current_attempt — the reply must stay on the round it answered."""

    async def gen() -> AsyncIterator[bytes]:
        accumulated: list[str] = []
        try:
            async for delta in stream_chat(
                api_settings, llm_messages, temperature=DIALOGUE_TEMPERATURE
            ):
                accumulated.append(delta)
                yield _sse(json.dumps({"delta": delta}, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            logger.exception("LLM stream failed for kp_id=%s", kp_id)
            yield _sse(
                json.dumps(
                    {"message": "LLM 调用失败，请稍后重试"},
                    ensure_ascii=False,
                ),
                event="error",
            )
            return

        full_content = "".join(accumulated)
        if not full_content:
            yield _sse(
                json.dumps({"message": "LLM 没有返回内容"}, ensure_ascii=False),
                event="error",
            )
            return

        async with SessionLocal() as write_db:
            assistant_msg = Message(
                kp_id=kp_id,
                attempt=attempt,
                role=MessageRole.assistant,
                content=full_content,
            )
            write_db.add(assistant_msg)
            await write_db.commit()
            await write_db.refresh(assistant_msg)
            assistant_id = str(assistant_msg.id)

        yield _sse(json.dumps({"id": assistant_id}), event="done")

    return gen()


def _streaming_response(gen: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_model=list[MessageOut])
async def list_messages(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[Message]:
    kp = await _load_kp(course_id, kp_id, db)
    if kp.status == KPStatus.untouched:
        kp.status = KPStatus.in_progress
        await db.commit()
    # Only the current attempt's conversation — prior rounds live in the
    # diary, not in the live chat pane.
    result = await db.execute(
        select(Message)
        .where(Message.kp_id == kp_id, Message.attempt == kp.current_attempt)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


@router.post("")
async def send_message(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    payload: SendMessageIn,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    kp = await _load_kp(course_id, kp_id, db)
    api_settings = await load_api_settings(db)

    # Capture the round once. The user row, the LLM history, and the
    # assistant row (written later in its own session) must all agree on
    # this attempt even if a retry bumps current_attempt mid-request.
    attempt = kp.current_attempt

    user_msg = Message(
        kp_id=kp.id,
        attempt=attempt,
        role=MessageRole.user,
        content=payload.content,
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    history_result = await db.execute(
        select(Message)
        .where(Message.kp_id == kp.id, Message.attempt == attempt)
        .order_by(Message.created_at)
    )
    history = list(history_result.scalars().all())

    llm_messages = await assemble_chat_messages(
        db,
        course_id=course_id,
        kp=kp,
        history=history,
        query_text=payload.content,
        api_settings=api_settings,
    )
    return _streaming_response(
        _stream_assistant_response(
            kp.id, attempt, api_settings, llm_messages
        )
    )


@router.post("/opening")
async def open_dialogue(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Generate the teacher's opening line when the KP has no history yet.

    No-op (returns an SSE error event) if any messages already exist for this KP.
    """
    kp = await _load_kp(course_id, kp_id, db)
    attempt = kp.current_attempt

    # "Already open" is per attempt: after a retry the new round has no
    # messages yet, so the opening line should be generated again.
    existing = await db.execute(
        select(Message.id)
        .where(Message.kp_id == kp.id, Message.attempt == attempt)
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        async def already_open() -> AsyncIterator[bytes]:
            yield _sse(
                json.dumps({"message": "对话已开始"}, ensure_ascii=False),
                event="error",
            )

        return _streaming_response(already_open())

    if kp.status == KPStatus.untouched:
        kp.status = KPStatus.in_progress
        await db.commit()

    api_settings = await load_api_settings(db)
    llm_messages = await assemble_chat_messages(
        db,
        course_id=course_id,
        kp=kp,
        history=[],
        query_text="",
        api_settings=api_settings,
        append_user=OPENING_USER_PROMPTS[lang_of(api_settings)],
    )
    return _streaming_response(
        _stream_assistant_response(
            kp.id, attempt, api_settings, llm_messages
        )
    )
