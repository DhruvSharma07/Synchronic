"""
Async SQLAlchemy engine/session setup.

Reads DATABASE_URL from the environment (see .env.example at the repo root).
docker-compose provides a plain `postgresql://` URL; SQLAlchemy's async engine
needs the `+asyncpg` driver marker, so it is added here if missing.
"""
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def _async_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


DATABASE_URL = _async_url(
    os.getenv("DATABASE_URL", "postgresql://synchronic:synchronic@127.0.0.1:5432/synchronic")
)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes"),
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables from the models if they don't exist yet.

    A transaction-scoped advisory lock serialises this across uvicorn workers
    so concurrent starts can't race each other inside create_all. Replace with
    Alembic migrations under infra/migrations once the schema needs repeatable,
    reviewable changes (create_all never alters existing tables).
    """
    import models  # noqa: F401  (registers tables on Base.metadata)

    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        await conn.run_sync(Base.metadata.create_all)
