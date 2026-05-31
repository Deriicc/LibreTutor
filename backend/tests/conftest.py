import os

# Tests never call the real API — see monkeypatch usage in test_builder.py.
# Global CHAT_API_KEY is optional (per-user api_settings is the runtime
# path); set a placeholder for any code path that still reads the global.
os.environ.setdefault("CHAT_API_KEY", "test-not-used")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/self_learning")
# Keep NullPool in tests to avoid cross-event-loop reuse issues in pytest-asyncio.
os.environ.setdefault("TESTING", "1")
