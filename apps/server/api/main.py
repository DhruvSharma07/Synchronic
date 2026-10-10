"""
Synchronic REST API: auth, users, documents and sharing.

Live document content is not served here - that is the sync service
(apps/server/sync). This API owns metadata and permissions, and tells the sync
service about access changes over Redis pub/sub.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from database import engine, init_models
from redis_client import close_redis, get_redis
from routers import auth, documents, users

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("synchronic.api")

IS_PRODUCTION = os.getenv("APP_ENV", "development") == "production"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]


async def _init_db_with_retry(attempts: int = 30, delay: float = 1.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await init_models()
            return
        except Exception as exc:  # DB still booting, or a concurrent worker won the race
            if attempt == attempts:
                raise
            logger.warning("Database not ready (%d/%d): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_db_with_retry()
    yield
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title="Synchronic API",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)


@app.get("/health")
def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    """Readiness: Postgres and Redis are reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await (await get_redis()).ping()
    except Exception:
        logger.exception("Readiness check failed")
        raise HTTPException(503, "Not ready")
    return {"status": "ok"}
