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
