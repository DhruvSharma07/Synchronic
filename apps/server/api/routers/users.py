"""
GET/PATCH /users/me, GET /users/search
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import UpdateUserRequest, UserResponse
from security import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/search", response_model=list[UserResponse])
async def search_users(
    q: str = Query(min_length=1),
    _current_user: User = Depends(get_current_user),  # must be signed in to search
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{q}%"
    result = await db.execute(
        select(User)
        .where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
        .limit(10)
    )
    return result.scalars().all()
