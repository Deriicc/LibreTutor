from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Set PRODUCTION=true in the deployed .env. Hides the FastAPI
    # docs/openapi routes and requires ENCRYPTION_KEY (enforced below).
    # Default False keeps local HTTP dev working.
    production: bool = False

    # Fernet key for encrypting the api_settings blob at rest. Empty in
    # dev = plaintext pass-through; required in production (enforced
    # below). Generate: python -c "from cryptography.fernet import
    # Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/self_learning"
    # The student app dev origin (Vite, port 5173). Override in production
    # with the deployed frontend origin(s).
    cors_origins: list[str] = ["http://localhost:5173"]
    upload_dir: str = "uploads"
    max_pdf_bytes: int = 50 * 1024 * 1024
    # Raw upload guard only — the image is re-encoded/downscaled on
    # upload, so this is an abuse/decompression-bomb ceiling, not a
    # quality limit. Generous so ordinary phone photos never fail.
    max_avatar_bytes: int = 20 * 1024 * 1024

    # Global chat LLM config. These are app-level defaults; the in-app
    # Settings page (AppSettings.api_settings) overrides them when set.
    # Optional so the app boots without keys (the user fills them in on
    # the Settings page).
    chat_api_key: str = ""
    chat_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-chat"
    # "openai" (OpenAI-compatible) | "anthropic". Stored/echoed only — the
    # client is always OpenAI-compatible; "anthropic" means point base_url
    # at an Anthropic OpenAI-compatible proxy.
    chat_provider: str = "openai"

    # Max parallel LLM calls when slicing a PDF into KPs (issue 17). Bounded to
    # respect DeepSeek per-account rate limits.
    kp_extraction_concurrency: int = 5

    # Char budget for prior-diary history fed into a new diary entry
    # (ADR-0023). Generous default ≈ whole book for the configured
    # long-context model; oldest entries are dropped first if exceeded,
    # so correctness never depends on the context window size.
    diary_context_char_budget: int = 200_000

    # Issue 19: optional OpenAI-compatible embedding endpoint. If
    # `embedding_api_key` is empty (the default), VectorSearch falls back to
    # the hash-based deterministic embedding — semantics are coarser but no
    # second API key is required.
    # Defaults wired to Aliyun DashScope `text-embedding-v4` (1024-dim native).
    # Override via .env to switch providers. The pgvector column dimension
    # (`EMBEDDING_DIM` in models/document_chunk.py) must match what the chosen
    # model returns — changing it needs a new migration.
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        # Pin the browser-accessible origins in production — refuse to boot
        # on a wildcard '*' rather than silently serving every origin. Dev
        # (production=False) is unaffected.
        if self.production and "*" in self.cors_origins:
            raise ValueError(
                "production=true with wildcard CORS origin '*' is unsafe "
                "— set CORS_ORIGINS to the explicit list of https frontend "
                "origins"
            )
        # Fail closed: never run production with the API keys stored
        # unencrypted in the DB.
        if self.production and not self.encryption_key.strip():
            raise ValueError(
                "production=true requires ENCRYPTION_KEY so the API keys "
                "are encrypted at rest — generate one with "
                "Fernet.generate_key()"
            )
        return self


settings = Settings()
