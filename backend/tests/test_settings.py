"""App settings router + resolver unit tests (project style: call route
coroutines directly; no httpx). Settings live in the single AppSettings row."""
import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.db import SessionLocal
from app.models import AppSettings
from app.settings_router import SettingsIn, get_settings, put_settings
from app.user_llm import LLMNotConfigured, resolve_chat, resolve_embedding


async def _reset(db) -> None:
    await db.execute(delete(AppSettings))
    await db.commit()


async def test_get_defaults_then_put_persists():
    async with SessionLocal() as db:
        await _reset(db)
        try:
            out = await get_settings(db=db)
            assert out.chat_api_key == ""
            assert out.chat_provider == "openai"  # default backfilled

            await put_settings(
                SettingsIn(
                    chat_api_key="sk-abc",
                    chat_model="m1",
                    chat_base_url="https://x",
                    chat_provider="anthropic",
                ),
                db=db,
            )
            fresh = await db.get(AppSettings, 1)
            assert fresh.api_settings["chat_api_key"] == "sk-abc"
            assert fresh.api_settings["chat_provider"] == "anthropic"
            echoed = await get_settings(db=db)
            assert echoed.chat_model == "m1"
        finally:
            await _reset(db)


async def test_put_rejects_bad_provider():
    async with SessionLocal() as db:
        await _reset(db)
        try:
            with pytest.raises(HTTPException) as ei:
                await put_settings(SettingsIn(chat_provider="gemini"), db=db)
            assert ei.value.status_code == 422
        finally:
            await _reset(db)


async def test_api_settings_encrypted_at_rest(monkeypatch):
    """With ENCRYPTION_KEY set, the key is unreadable in the raw column
    but transparently decrypted on a normal ORM read (M5)."""
    from cryptography.fernet import Fernet
    from sqlalchemy import text

    from app import config

    monkeypatch.setattr(
        config.settings, "encryption_key", Fernet.generate_key().decode()
    )
    async with SessionLocal() as db:
        await _reset(db)
        await put_settings(
            SettingsIn(chat_api_key="sk-secret-xyz", chat_model="m"),
            db=db,
        )
    # Fresh session: raw column is ciphertext, ORM read decrypts.
    async with SessionLocal() as db2:
        try:
            raw = (
                await db2.execute(
                    text("SELECT api_settings::text FROM app_settings WHERE id = 1"),
                )
            ).scalar()
            assert "sk-secret-xyz" not in raw
            assert "_enc" in raw
            fresh = await db2.get(AppSettings, 1)
            assert fresh.api_settings["chat_api_key"] == "sk-secret-xyz"
        finally:
            await _reset(db2)


def test_resolve_chat_requires_key_and_model():
    with pytest.raises(LLMNotConfigured):
        resolve_chat({})
    with pytest.raises(LLMNotConfigured):
        resolve_chat({"chat_api_key": "k"})  # model missing
    client, model = resolve_chat({"chat_api_key": "k", "chat_model": "m"})
    assert model == "m"


def test_resolve_embedding_optional():
    assert resolve_embedding({}) is None
    resolved = resolve_embedding(
        {"embedding_api_key": "k", "embedding_model": "e"}
    )
    assert resolved is not None and resolved[1] == "e"
