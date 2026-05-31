import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


# Tests set TESTING=1 to keep NullPool (avoids cross-event-loop issues in
# pytest-asyncio). In production, use a connection pool so connections are
# reused across requests instead of opened fresh for every query.
_testing = bool(os.getenv("TESTING"))
_db_url = settings.database_url
# Railway injects postgresql:// but async engine needs postgresql+asyncpg://
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(
    _db_url,
    echo=False,
    future=True,
    poolclass=NullPool if _testing else AsyncAdaptedQueuePool,
    **({} if _testing else {"pool_size": 20, "max_overflow": 20, "pool_pre_ping": True}),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
