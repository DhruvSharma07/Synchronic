"""
REST-layer enforcement: resolves the caller's role on a document and gates
routes with `require_role(minimum)`.

Responses follow docs/requirements.md: 404 (never 403) when the caller has no
access at all, so a document's existence isn't confirmed to outsiders; 403 only
when they have *some* access but not enough for the action.
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Document, DocumentPermission, User
from roles import ROLE_RANK, compute_role, has_role
from security import get_current_user

__all__ = ["ROLE_RANK", "DocumentAccess", "has_role", "require_role", "resolve_role"]


@dataclass
class DocumentAccess:
    document: Document
    role: str
    user: User


async def resolve_role(db: AsyncSession, document: Document, user: User) -> str | None:
    result = await db.execute(
        select(DocumentPermission.role).where(
            DocumentPermission.document_id == document.id,
            DocumentPermission.user_id == user.id,
        )
    )
    return compute_role(
        document.owner_id,
        user.id,
        result.scalar_one_or_none(),
        document.is_link_shareable,
        document.link_share_role,
    )


def require_role(minimum: str):
    async def dependency(
        doc_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> DocumentAccess:
        not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        try:
            document = await db.get(Document, uuid.UUID(doc_id))
        except ValueError:
            raise not_found
        if document is None:
            raise not_found
        role = await resolve_role(db, document, user)
        if role is None:
            raise not_found
        if not has_role(role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do that")
        return DocumentAccess(document=document, role=role, user=user)

    return dependency
