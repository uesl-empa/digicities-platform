# SPDX-License-Identifier: Apache-2.0
"""Workspace catalog repository. Every function is a no-op / empty when the DB is
disabled (no ``DATABASE_URL``), so callers never need to branch on it."""
from __future__ import annotations

import json
from typing import Optional

from .models import Base, Workspace
from .session import engine, session


def init_db() -> None:
    """Create tables if the DB is enabled. (Alembic takes over once the schema evolves.)"""
    eng = engine()
    if eng is not None:
        Base.metadata.create_all(eng)


def upsert(row: dict) -> None:
    """Insert or update a workspace's catalog row from discovery. Ownership/visibility are
    NOT overwritten once set (discovery only refreshes descriptive metadata)."""
    s = session()
    if s is None:
        return
    try:
        obj = s.get(Workspace, row["id"])
        created = obj is None
        if created:
            obj = Workspace(id=row["id"], visibility="shared")
            s.add(obj)
        obj.name = row.get("name") or obj.name or row["id"]
        obj.backend = row.get("backend") or "local"
        obj.graphdb_repo = row.get("graphdb_repo") or row["id"]
        obj.description = row.get("description") or obj.description or ""
        obj.tags = json.dumps(row.get("tags") or [])
        obj.protected = bool(row.get("protected"))
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def set_owner(ws_id: str, owner_id: str, visibility: str = "private") -> None:
    """Assign a workspace's owner + visibility (on create). Creates the row if missing."""
    s = session()
    if s is None:
        return
    try:
        obj = s.get(Workspace, ws_id)
        if obj is None:
            obj = Workspace(id=ws_id, graphdb_repo=ws_id)
            s.add(obj)
        obj.owner_id = owner_id
        obj.visibility = "private" if str(visibility).lower().startswith("priv") else "shared"
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def grant_editor(ws_id: str, user_id: str) -> None:
    s = session()
    if s is None:
        return
    try:
        from .models import WorkspaceAcl
        if s.get(WorkspaceAcl, {"workspace_id": ws_id, "user_id": user_id}) is None:
            s.add(WorkspaceAcl(workspace_id=ws_id, user_id=user_id, role="editor"))
            s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def visible_to(user_id: Optional[str]) -> Optional[set]:
    """The set of workspace ids the caller may SEE. A **private** workspace is only in the
    set for its owner (or an ACL editor); **shared** (and legacy unowned=shared) are visible
    to everyone, INCLUDING anonymous callers — so a private workspace is never listed for a
    signed-out user. Returns None only when the DB is disabled (no visibility data → show all)."""
    s = session()
    if s is None:
        return None
    try:
        from sqlalchemy import or_, select
        from .models import WorkspaceAcl
        conds = [Workspace.visibility == "shared"]
        if user_id is not None:
            conds.append(Workspace.owner_id == user_id)
        ids = set(s.scalars(select(Workspace.id).where(or_(*conds))).all())
        if user_id is not None:
            ids |= set(s.scalars(select(WorkspaceAcl.workspace_id).where(
                WorkspaceAcl.user_id == user_id)).all())
        return ids
    finally:
        s.close()


def can_edit(ws_id: str, user_id: Optional[str]) -> bool:
    """Owner or an ACL editor may edit/delete. Unowned (legacy) workspaces stay editable by
    anyone (today's behaviour); an OWNED workspace is not editable anonymously. DB off = allow."""
    s = session()
    if s is None:
        return True
    try:
        from .models import WorkspaceAcl
        w = s.get(Workspace, ws_id)
        if w is None or w.owner_id is None:
            return True                              # unowned / legacy
        if user_id is None:
            return False                             # owned workspace, anonymous caller
        if w.owner_id == user_id:
            return True
        return s.get(WorkspaceAcl, {"workspace_id": ws_id, "user_id": user_id}) is not None
    finally:
        s.close()


def get(ws_id: str) -> Optional[dict]:
    s = session()
    if s is None:
        return None
    try:
        obj = s.get(Workspace, ws_id)
        return _to_dict(obj) if obj else None
    finally:
        s.close()


def list_all() -> list[dict]:
    s = session()
    if s is None:
        return []
    try:
        from sqlalchemy import select
        return [_to_dict(w) for w in s.scalars(select(Workspace)).all()]
    finally:
        s.close()


def _to_dict(w: Workspace) -> dict:
    return {
        "id": w.id, "name": w.name, "owner_id": w.owner_id, "visibility": w.visibility,
        "backend": w.backend, "graphdb_repo": w.graphdb_repo, "description": w.description,
        "tags": json.loads(w.tags or "[]"), "protected": w.protected,
        "created_at": w.created_at, "updated_at": w.updated_at,
    }
