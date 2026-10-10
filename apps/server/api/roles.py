"""
Pure role-resolution logic (no framework imports so it is trivially testable).

The sync service keeps an identical copy in apps/server/sync/roles.py - the two
services are built and deployed independently, and each must resolve roles on
its own (README: "no inherited trust between layers"). Keep them in sync.
"""
from __future__ import annotations

ROLE_RANK = {"viewer": 1, "commenter": 2, "editor": 3, "owner": 4}


def has_role(role: str | None, minimum: str) -> bool:
    return role is not None and ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


def compute_role(
    owner_id,
    user_id,
    permission_role: str | None,
    is_link_shareable: bool,
    link_share_role: str | None,
) -> str | None:
    """Highest role the user holds on a document, or None for no access.

    Ownership is decided only by documents.owner_id, never by a permission row.
    """
    if str(owner_id) == str(user_id):
        return "owner"

    candidates: list[str] = []
    if permission_role in ROLE_RANK:
        # A stray 'owner' row for a non-owner must never grant ownership.
        candidates.append("editor" if permission_role == "owner" else permission_role)
    if is_link_shareable and link_share_role in ROLE_RANK and link_share_role != "owner":
        candidates.append(link_share_role)

    if not candidates:
        return None
    return max(candidates, key=lambda r: ROLE_RANK[r])
