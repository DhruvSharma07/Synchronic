"""
Password hashing, JWT issuing/verification, and the get_current_user
dependency used by every authenticated route.

Access tokens are short-lived (15 min) and stateless - any request with a
validly-signed, non-expired token is accepted, with no database or Redis
lookup per request. Refresh tokens are longer-lived (30 days) and checked
against an allowlist in Redis keyed by their `jti` (a unique token id):
issuing one writes its jti to Redis, and /auth/logout deletes it. Without
that check, a leaked refresh token would stay valid until it expired
naturally no matter what logout did, since JWTs can't be "un-signed".
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from redis_client import get_redis

logger = logging.getLogger("synchronic.security")

_DEV_SECRET = "change-me-dev-secret"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_SECRET)
if os.getenv("APP_ENV", "development") == "production" and (
    JWT_SECRET == _DEV_SECRET or len(JWT_SECRET) < 32
):
    raise RuntimeError("JWT_SECRET must be set to a random value of 32+ characters in production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# auto_error=False so a missing header yields 401 (not FastAPI's default 403),
# which is what the client uses to decide to refresh its token.
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def _create_token(
    user_id: uuid.UUID, token_type: str, ttl: timedelta, jti: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "type": token_type, "iat": now, "exp": now + ttl}
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, "access", ACCESS_TOKEN_TTL)


async def create_refresh_token(user_id: uuid.UUID) -> str:
    jti = str(uuid.uuid4())
    token = _create_token(user_id, "refresh", REFRESH_TOKEN_TTL, jti=jti)
    redis = await get_redis()
    # The Redis key existing at all *is* the "still valid" check - deleting
    # it on logout revokes the token immediately, before its natural expiry.
    await redis.set(f"refresh:{jti}", str(user_id), ex=int(REFRESH_TOKEN_TTL.total_seconds()))
    return token


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return payload


async def verify_refresh_token(token: str) -> tuple[uuid.UUID, str]:
    payload = _decode_token(token, "refresh")
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    redis = await get_redis()
    stored_user_id = await redis.get(f"refresh:{jti}")
    if stored_user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    return uuid.UUID(payload["sub"]), jti


async def revoke_refresh_token(jti: str) -> None:
    redis = await get_redis()
    await redis.delete(f"refresh:{jti}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = _decode_token(credentials.credentials, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


async def enforce_rate_limit(key: str, limit: int = 10, window_seconds: int = 60) -> None:
    """Fixed-window counter in Redis; raises 429 once `limit` is exceeded."""
    redis = await get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, please try again shortly"
        )


async def clear_rate_limit(key: str) -> None:
    redis = await get_redis()
    await redis.delete(key)
