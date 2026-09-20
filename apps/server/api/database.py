"""
Async SQLAlchemy engine/session setup.

Reads DATABASE_URL from the environment (see .env.example at the repo
root). docker-compose sets it as a plain `postgresql://` URL; SQLAlchemy's
async engine needs the `+asyncpg` driver marker, so it's added here if
missing rather than requiring every consumer of DATABASE_URL to know that.
"""
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://syncronix:syncronix@localhost:5432/syncronix"
)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables from the models below if they don't exist yet.

    This is a Phase 1 shortcut so the scaffold works without extra setup.
    Once the schema stabilizes, replace this with real Alembic migrations
    under infra/migrations (see README "Getting started") - auto-creating
    tables from models is fine for early dev, not for a team that needs
    repeatable, reviewable schema changes.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
