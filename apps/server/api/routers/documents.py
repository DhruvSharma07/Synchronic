"""
Document CRUD, sharing and ownership transfer. Every route is gated by
require_role() and publishes a Redis event on access changes so live WebSocket
sessions are downgraded or dropped immediately.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Document, DocumentPermission, User
from permissions import DocumentAccess, has_role, require_role
from redis_client import publish_permission_event
from schemas import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    PermissionEntry,
    PermissionGrant,
    TransferOwnershipRequest,
)
from security import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])


def _response(doc: Document, role: str) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        owner_id=doc.owner_id,
        role=role,
        is_link_shareable=doc.is_link_shareable,
        link_share_role=doc.link_share_role,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Documents the caller owns or has been explicitly shared on."""
    stmt = (
        select(Document, DocumentPermission.role)
        .outerjoin(
            DocumentPermission,
            and_(
                DocumentPermission.document_id == Document.id,
                DocumentPermission.user_id == user.id,
            ),
        )
        .where(or_(Document.owner_id == user.id, DocumentPermission.user_id == user.id))
        .order_by(Document.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        _response(doc, "owner" if doc.owner_id == user.id else perm_role)
        for doc, perm_role in rows
    ]


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = Document(id=uuid.uuid4(), owner_id=user.id, title=payload.title.strip() or "Untitled document")
    db.add(doc)
    await db.flush()  # documents row must exist before the permission row's FK
    db.add(DocumentPermission(document_id=doc.id, user_id=user.id, role="owner", granted_by=user.id))
    await db.commit()
    await db.refresh(doc)
    return _response(doc, "owner")


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(access: DocumentAccess = Depends(require_role("viewer"))):
    return _response(access.document, access.role)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    payload: DocumentUpdate,
    access: DocumentAccess = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    doc = access.document
    sharing_changed = False

    if payload.title is not None:
        if not has_role(access.role, "editor"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do that")
        doc.title = payload.title.strip() or doc.title

    if payload.is_link_shareable is not None or payload.link_share_role is not None:
        if not has_role(access.role, "owner"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change link sharing")
        if payload.is_link_shareable is not None:
            doc.is_link_shareable = payload.is_link_shareable
        if payload.link_share_role is not None:
            doc.link_share_role = payload.link_share_role
        sharing_changed = True

    await db.commit()
    await db.refresh(doc)
    if sharing_changed:
        await publish_permission_event(doc.id)  # re-check everyone in the room
    return _response(doc, access.role)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    access: DocumentAccess = Depends(require_role("owner")),
    db: AsyncSession = Depends(get_db),
):
    doc_id = access.document.id
    await db.delete(access.document)  # permissions + snapshots go via ON DELETE CASCADE
    await db.commit()
    await publish_permission_event(doc_id, deleted=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Sharing -----------------------------------------------------------------


@router.get("/{doc_id}/permissions", response_model=list[PermissionEntry])
async def list_permissions(
    access: DocumentAccess = Depends(require_role("owner")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(DocumentPermission, User)
            .join(User, User.id == DocumentPermission.user_id)
            .where(DocumentPermission.document_id == access.document.id)
            .order_by(DocumentPermission.granted_at)
        )
    ).all()
    return [PermissionEntry(user=u, role=p.role, granted_at=p.granted_at) for p, u in rows]


@router.post("/{doc_id}/permissions", response_model=PermissionEntry)
async def grant_permission(
    payload: PermissionGrant,
    access: DocumentAccess = Depends(require_role("owner")),
    db: AsyncSession = Depends(get_db),
):
    if payload.user_id is not None:
        target = await db.get(User, payload.user_id)
    else:
        target = (
            await db.execute(select(User).where(func.lower(User.email) == payload.email.lower()))
        ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user found for that email")
    if target.id == access.document.owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The owner already has full access")

    perm = await db.get(DocumentPermission, (access.document.id, target.id))
    if perm is None:
        perm = DocumentPermission(
            document_id=access.document.id,
            user_id=target.id,
            role=payload.role,
            granted_by=access.user.id,
        )
        db.add(perm)
    else:
        perm.role = payload.role
        perm.granted_by = access.user.id
    await db.commit()
    await db.refresh(perm)
    await publish_permission_event(access.document.id, target.id)
    return PermissionEntry(user=target, role=perm.role, granted_at=perm.granted_at)


@router.delete("/{doc_id}/permissions/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    user_id: uuid.UUID,
    access: DocumentAccess = Depends(require_role("owner")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == access.document.owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The owner's access can't be removed")
    perm = await db.get(DocumentPermission, (access.document.id, user_id))
    if perm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user doesn't have access")
    await db.delete(perm)
    await db.commit()
    await publish_permission_event(access.document.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{doc_id}/transfer-ownership", response_model=DocumentResponse)
async def transfer_ownership(
    payload: TransferOwnershipRequest,
    access: DocumentAccess = Depends(require_role("owner")),
    db: AsyncSession = Depends(get_db),
):
    doc = access.document
    if payload.user_id == doc.owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That user already owns the document")
    new_owner = await db.get(User, payload.user_id)
    if new_owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    previous_owner_id = doc.owner_id
    doc.owner_id = new_owner.id

    new_perm = await db.get(DocumentPermission, (doc.id, new_owner.id))
    if new_perm is None:
        db.add(
            DocumentPermission(
                document_id=doc.id, user_id=new_owner.id, role="owner", granted_by=access.user.id
            )
        )
    else:
        new_perm.role = "owner"
    old_perm = await db.get(DocumentPermission, (doc.id, previous_owner_id))
    if old_perm is not None:
        old_perm.role = "editor"  # previous owner keeps edit access
    await db.commit()
    await db.refresh(doc)

    await publish_permission_event(doc.id, previous_owner_id)
    await publish_permission_event(doc.id, new_owner.id)
    return _response(doc, "editor")
