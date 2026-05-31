"""LLM / embedding client resolution (BYO key).

Every LLM call resolves keys from the app-wide `AppSettings.api_settings`
(set on the in-app Settings page), falling back to the platform default
keys (`settings.chat_api_key` / `embedding_api_key`, set via env) when
unset. With neither a configured key nor a platform default, chat raises
LLMNotConfigured and embedding degrades to the local hash embed.

`chat_provider` is "openai" | "anthropic"; the client is always the
OpenAI-compatible SDK either way ("anthropic" just means pointing
`chat_base_url` at an Anthropic OpenAI-compatible proxy).
"""

from openai import AsyncOpenAI

from app.config import settings


async def load_api_settings(db) -> dict:
    """Load the app-wide api_settings (singleton row id=1). Returns {} when
    unset — resolve_chat/resolve_embedding then fall back to env defaults."""
    from app.models import AppSettings

    row = await db.get(AppSettings, 1)
    return (row.api_settings if row and row.api_settings else {}) or {}


class LLMNotConfigured(Exception):
    """The user hasn't configured the required API settings.

    Maps to HTTP 400 on request paths and to a task-failed status with a
    user-readable message on background paths.
    """


def _norm(v: object) -> str:
    return str(v).strip() if v is not None else ""


# Cache clients by (api_key, base_url) so we don't build a new httpx
# client on every call. Keyed by credentials, not by user.
_chat_clients: dict[tuple[str, str], AsyncOpenAI] = {}
_embed_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def resolve_chat(api_settings: dict | None) -> tuple[AsyncOpenAI, str]:
    """(client, model) for the user's chat LLM. Falls back to the platform
    default (settings.chat_*) when the user has no key. Raises
    LLMNotConfigured only if neither the user nor the platform has one."""
    s = api_settings or {}
    key = _norm(s.get("chat_api_key"))
    if key:
        model = _norm(s.get("chat_model"))
        base = _norm(s.get("chat_base_url")) or None
    else:
        # No per-user key → use the platform default keys (env). Take the
        # default as a coherent set so a user key never mixes with a global
        # model from a different provider.
        key = _norm(settings.chat_api_key)
        model = _norm(settings.chat_model)
        base = _norm(settings.chat_base_url) or None
    if not key or not model:
        raise LLMNotConfigured("请先在「设置」页配置 Chat API Key 与模型")
    ck = (key, base or "")
    client = _chat_clients.get(ck)
    if client is None:
        client = AsyncOpenAI(api_key=key, base_url=base)
        _chat_clients[ck] = client
    return client, model


def resolve_embedding(
    api_settings: dict | None,
) -> tuple[AsyncOpenAI, str] | None:
    """(client, model) for the user's embedding endpoint, falling back to
    the platform default (settings.embedding_*) when the user has no key.
    Returns None only when neither is set — callers then use the local hash
    embed (offline degradation)."""
    s = api_settings or {}
    key = _norm(s.get("embedding_api_key"))
    if key:
        model = _norm(s.get("embedding_model")) or "text-embedding-v4"
        base = _norm(s.get("embedding_base_url")) or None
    else:
        key = _norm(settings.embedding_api_key)
        if not key:
            return None
        model = _norm(settings.embedding_model) or "text-embedding-v4"
        base = _norm(settings.embedding_base_url) or None
    ck = (key, base or "")
    client = _embed_clients.get(ck)
    if client is None:
        client = AsyncOpenAI(api_key=key, base_url=base)
        _embed_clients[ck] = client
    return client, model
