"""Token validation and role lookup, independent of the REST API."""
import os
import uuid

from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from roles import compute_role

_DEV_SECRET = "change-me-dev-secret"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_SECRET)
JWT_ALGORITHM = "HS256"
if os.getenv("APP_ENV", "development") == "production" and (
    JWT_SECRET == _DEV_SECRET or len(JWT_SECRET) < 32
):
    raise RuntimeError("JWT_SECRET must be set to a random value of 32+ characters in production")

LIVE_LABEL = "__live__"


class AuthError(Exception):
    pass


def decode_access_token(token: str | None) -> uuid.UUID:
    if not token:
        raise AuthError("missing token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise AuthError("wrong token type")
        return uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise AuthError("invalid token") from exc


def _async_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


class Store:
    """Postgres access for the sync server: roles and live document state."""

    def __init__(self, database_url: str):
        self.engine: AsyncEngine = create_async_engine(
            _async_url(database_url), pool_pre_ping=True, pool_size=5, max_overflow=5
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def resolve_role(self, document_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT d.owner_id, d.is_link_shareable, d.link_share_role, p.role
                        FROM documents d
                        LEFT JOIN document_permissions p
                          ON p.document_id = d.id AND p.user_id = :uid
                        WHERE d.id = :did
                        """
                    ),
                    {"did": document_id, "uid": user_id},
                )
            ).first()
        if row is None:
            return None
        owner_id, link_shareable, link_role, perm_role = row
        return compute_role(owner_id, user_id, perm_role, link_shareable, link_role)

    async def load_state(self, document_id: uuid.UUID) -> bytes | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT yjs_state FROM document_snapshots "
                        "WHERE document_id = :did AND label = :label"
                    ),
                    {"did": document_id, "label": LIVE_LABEL},
                )
            ).first()
        return bytes(row[0]) if row else None

    async def save_state(self, document_id: uuid.UUID, state: bytes) -> bool:
        """Upsert the live snapshot. Returns False if the document no longer exists."""
        async with self.engine.begin() as conn:
            exists = (
                await conn.execute(text("SELECT 1 FROM documents WHERE id = :did"), {"did": document_id})
            ).first()
            if exists is None:
                return False
            await conn.execute(
                text(
                    """
                    INSERT INTO document_snapshots (id, document_id, yjs_state, created_at, label)
                    VALUES (:id, :did, :state, now(), :label)
                    ON CONFLICT (document_id) WHERE label = '__live__'
                    DO UPDATE SET yjs_state = EXCLUDED.yjs_state, created_at = now()
                    """
                ),
                {"id": uuid.uuid4(), "did": document_id, "state": state, "label": LIVE_LABEL},
            )
            await conn.execute(
                text("UPDATE documents SET updated_at = now() WHERE id = :did"), {"did": document_id}
            )
        return True
