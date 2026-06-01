"""Chat turn assembly: turn KP state + chat history into the llm_messages
list ready to feed `stream_chat`.

Owns the read-side pipeline (page range → KPMaterial → RAG → 3-layer prompt)
that's identical for the regular `send_message` flow and the
`open_dialogue` flow. The two FastAPI handlers become thin shells around
`assemble_chat_messages` + the streaming helper in `chat.router`.

Pure read: this module does not write to the database. The handlers own
INSERTs (user message before send, assistant message after stream).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.socratic import build_system_prompt, count_turns
from app.lang import lang_of
from app.courses.embedding import fetch_page_range_chunks, search_top_k
from app.kp.loader import get_kp_material
from app.models import KnowledgePoint, Message


OPENING_USER_PROMPTS = {
    "zh": (
        "（学生刚进入此知识点，尚未发言。请参照 Few-shot 示例 1 的语气主动开场，"
        "用一句话邀请学生说说他对此 KP 的已有印象。）"
    ),
    "en": (
        "(The student just entered this knowledge point and hasn't spoken yet. "
        "Open proactively in the tone of Few-shot example 1, with one sentence "
        "inviting the student to share their existing impression of this KP.)"
    ),
}


def _kp_page_range(boundary: dict | None) -> tuple[int | None, int | None]:
    """Extract (page_start, page_end) from a KP boundary dict.
    Returns (None, None) for missing/invalid bounds."""
    try:
        b = boundary or {}
        ps = int(b.get("page_start") or 0) or None
        pe = int(b.get("page_end") or 0) or None
        if ps and pe and ps > pe:
            return None, None
        return ps, pe
    except (TypeError, ValueError):
        return None, None


def _build_retrieval_query(
    user_msg: str, kp_title: str, keyphrases: Sequence[str]
) -> str:
    """Anchor a potentially vague user message to the KP's semantic core.

    Prepend KP title + keyphrases so short/noisy messages (「嗯」「不懂」) still
    retrieve the right chunks. When the user message is substantive (>4 chars
    after strip) it is appended so topic-specific questions pull the right
    content.
    """
    kw = " ".join(keyphrases)
    anchor = f"{kp_title} {kw}".strip() if kw else kp_title
    stripped = user_msg.strip()
    if len(stripped) > 4:
        return f"{anchor} {stripped}"
    return anchor


async def _load_retrieval_chunks(
    db: AsyncSession,
    course_id: uuid.UUID,
    kp: KnowledgePoint,
    query_text: str,
    api_settings: dict | None = None,
) -> list[str]:
    """Fetch RAG chunks for this turn.

    When the KP has a page range, return all chunks overlapping it (no
    embedding call). Otherwise fall back to cosine top-k against a query
    anchored to KP title + keyphrases.
    """
    page_start, page_end = _kp_page_range(kp.boundary)
    if page_start and page_end:
        chunks = await fetch_page_range_chunks(course_id, page_start, page_end, db)
    else:
        material = await get_kp_material(db, kp.id)
        keyphrases = list(material.keyphrases) if material and material.keyphrases else []
        retrieval_query = _build_retrieval_query(query_text, kp.title, keyphrases)
        chunks = await search_top_k(
            api_settings, course_id, retrieval_query, db, k=5
        )
    return [c.text for c in chunks]


async def assemble_chat_messages(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    kp: KnowledgePoint,
    history: Sequence[Message],
    query_text: str,
    api_settings: dict | None = None,
    append_user: str | None = None,
) -> list[dict[str, str]]:
    """Build the LLM message list for one chat turn.

    Args:
      history: messages prior to this turn (chronological). For a regular
        send, history already includes the just-written user message —
        the LLM sees `[system, ...history including last user msg]`.
      query_text: text used to anchor RAG retrieval. Usually the latest
        user message content; pass empty string for the opening turn.
      append_user: when set, appended as a synthetic user-role message
        after history. Used by the opening flow with `OPENING_USER_PROMPTS`.

    Returns the llm_messages list ready to pass to `stream_chat`.
    """
    turn_count = count_turns(list(history))
    retrieval_texts = await _load_retrieval_chunks(
        db, course_id, kp, query_text, api_settings
    )
    system_content = await build_system_prompt(
        course_id,
        kp.id,
        kp.title,
        db,
        turn_count=turn_count,
        retrieval_chunks=retrieval_texts,
        lang=lang_of(api_settings),
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend({"role": m.role.value, "content": m.content} for m in history)
    if append_user is not None:
        messages.append({"role": "user", "content": append_user})
    return messages
