"""
POST /auth/register, /auth/login, /auth/logout, /auth/refresh
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    revoke_refresh_token,
    verify_password,
    verify_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Same error for "no such user" and "wrong password" - distinguishing
    # them would let a caller enumerate which emails are registered.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    access_token = create_access_token(user.id)
    refresh_token = await create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest):
    user_id, _jti = await verify_refresh_token(payload.refresh_token)
    return AccessTokenResponse(access_token=create_access_token(user_id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest):
    # Revokes the refresh token so it can't mint new access tokens. Any
    # access token already issued keeps working until it naturally expires
    # (at most 15 minutes) - a stronger guarantee would need an access-token
    # blocklist checked on every request, which trades latency for it.
    _user_id, jti = await verify_refresh_token(payload.refresh_token)
    await revoke_refresh_token(jti)
