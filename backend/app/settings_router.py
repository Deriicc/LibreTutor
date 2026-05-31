"""App-wide API settings (BYO key). The Settings page reads/writes the
single `AppSettings` row; chat falls back to the env defaults when unset,
so a user configures keys here before chat/grading/etc. work."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AppSettings
from app.user_llm import (
    LLMNotConfigured,
    load_api_settings,
    resolve_chat,
    resolve_embedding,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ALLOWED_PROVIDERS = {"", "openai", "anthropic"}
_KEYS = (
    "chat_base_url",
    "chat_api_key",
    "chat_model",
    "chat_provider",
    "embedding_api_key",
    "embedding_base_url",
    "embedding_model",
)


class SettingsIn(BaseModel):
    chat_base_url: str = Field(default="", max_length=512)
    chat_api_key: str = Field(default="", max_length=512)
    chat_model: str = Field(default="", max_length=128)
    chat_provider: str = Field(default="openai", max_length=32)
    embedding_api_key: str = Field(default="", max_length=512)
    embedding_base_url: str = Field(default="", max_length=512)
    embedding_model: str = Field(default="", max_length=128)


class SettingsOut(SettingsIn):
    pass


def _to_out(raw: dict | None) -> SettingsOut:
    raw = raw or {}
    data = {k: str(raw.get(k, "")) for k in _KEYS}
    if not data["chat_provider"]:
        data["chat_provider"] = "openai"
    # Keys are returned in full so the user can verify/edit them — this
    # is a single-tenant self-host product; the value never leaves the
    # owner's own session.
    return SettingsOut(**data)


@router.get("", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    return _to_out(await load_api_settings(db))


@router.put("", response_model=SettingsOut)
async def put_settings(
    payload: SettingsIn,
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    data = payload.model_dump()
    provider = (data.get("chat_provider") or "").strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="chat_provider 只能是 openai 或 anthropic",
        )
    data["chat_provider"] = provider or "openai"
    # Singleton row (id=1): assigning a fresh dict (not in-place mutation)
    # is detected by the ORM and flushed as an UPDATE.
    row = await db.get(AppSettings, 1)
    if row is None:
        db.add(AppSettings(id=1, api_settings=data))
    else:
        row.api_settings = data
    await db.commit()
    return _to_out(data)


class TestOut(BaseModel):
    ok: bool
    detail: str = ""


@router.post("/test-chat", response_model=TestOut)
async def test_chat(payload: SettingsIn) -> TestOut:
    """Probe the provided chat settings with a 1-token completion.
    Tests the values in the form (no save needed). The base_url is
    caller-controlled; this is a single-user self-host endpoint."""
    try:
        client, model = resolve_chat(payload.model_dump())
    except LLMNotConfigured as exc:
        return TestOut(ok=False, detail=str(exc))
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            stream=False,
        )
        return TestOut(ok=True, detail=f"连接成功（model={resp.model}）")
    except Exception as exc:  # noqa: BLE001
        return TestOut(ok=False, detail=str(exc)[:500])


@router.post("/test-embedding", response_model=TestOut)
async def test_embedding(payload: SettingsIn) -> TestOut:
    """Probe the provided embedding settings with one embed call."""
    resolved = resolve_embedding(payload.model_dump())
    if resolved is None:
        return TestOut(ok=False, detail="未填写 Embedding API Key")
    client, model = resolved
    try:
        resp = await client.embeddings.create(
            model=model, input="ping", dimensions=64
        )
        return TestOut(
            ok=True, detail=f"连接成功（dim={len(resp.data[0].embedding)}）"
        )
    except Exception as exc:  # noqa: BLE001
        return TestOut(ok=False, detail=str(exc)[:500])
