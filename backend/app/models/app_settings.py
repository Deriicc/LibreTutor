from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.crypto import EncryptedJSONB
from app.db import Base


class AppSettings(Base):
    """Single-row, app-wide settings for the single-user build.

    Holds the BYO LLM/embedding API keys (encrypted at rest) that the
    in-app Settings page reads and writes. There is exactly one row,
    pinned to id=1; see `app.user_llm.load_api_settings`.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False, default=1
    )
    # LLM/embedding overrides (BYO key). Keys: chat_base_url, chat_api_key,
    # chat_model, chat_provider, embedding_api_key, embedding_base_url,
    # embedding_model. Falls back to the env defaults when unset.
    api_settings: Mapped[dict] = mapped_column(
        EncryptedJSONB, nullable=False, server_default="{}", default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
