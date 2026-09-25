"""
Async SQLAlchemy engine/session setup.

Reads DATABASE_URL from the environment (see .env.example at the repo
root). docker-compose sets it as a plain `postgresql://` URL; SQLAlchemy's
async engine needs the `+asyncpg` driver marker, so it's added here if
missing rather than requiring every consumer of DATABASE_URL to know that.
"""
import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://syncronix:syncronix@127.0.0.1:5432/syncronix"
)

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1
    )

print("DATABASE_URL:", DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=True
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session