# SPDX-License-Identifier: Apache-2.0
"""User accounts repository. No-op / None when the DB is disabled (no DATABASE_URL)."""
from __future__ import annotations

import uuid
from typing import Optional

from .models import User
from .session import session


def create_user(email: str, password_hash: str, display_name: str = "",
                is_admin: bool = False) -> Optional[dict]:
    s = session()
    if s is None:
        return None
    try:
        uid = uuid.uuid4().hex
        s.add(User(id=uid, email=email.strip().lower(), password_hash=password_hash,
                   display_name=display_name or email.split("@")[0], is_admin=is_admin))
        s.commit()
        return {"id": uid, "email": email.strip().lower(), "display_name": display_name,
                "is_admin": is_admin}
    except Exception:
        s.rollback()
        return None
    finally:
        s.close()


def get_by_email(email: str) -> Optional[dict]:
    s = session()
    if s is None:
        return None
    try:
        from sqlalchemy import select
        u = s.scalars(select(User).where(User.email == email.strip().lower())).first()
        return _to_dict(u) if u else None
    finally:
        s.close()


def get_user(user_id: str) -> Optional[dict]:
    s = session()
    if s is None:
        return None
    try:
        u = s.get(User, user_id)
        return _to_dict(u) if u else None
    finally:
        s.close()


def list_users() -> list[dict]:
    s = session()
    if s is None:
        return []
    try:
        from sqlalchemy import select
        return [_to_dict(u) for u in s.scalars(select(User).order_by(User.email)).all()]
    finally:
        s.close()


def set_admin(email: str, is_admin: bool = True) -> bool:
    s = session()
    if s is None:
        return False
    try:
        from sqlalchemy import select
        u = s.scalars(select(User).where(User.email == email.strip().lower())).first()
        if u is None:
            return False
        u.is_admin = is_admin
        s.commit()
        return True
    except Exception:
        s.rollback()
        return False
    finally:
        s.close()


def delete_user(email: str) -> bool:
    """Remove an account and its ACL grants. Workspaces it OWNED keep the dangling
    owner_id (invisible to non-admins) — reassign them via the assign route first."""
    s = session()
    if s is None:
        return False
    try:
        from sqlalchemy import delete, select
        from .models import WorkspaceAcl
        u = s.scalars(select(User).where(User.email == email.strip().lower())).first()
        if u is None:
            return False
        s.execute(delete(WorkspaceAcl).where(WorkspaceAcl.user_id == u.id))
        s.delete(u)
        s.commit()
        return True
    except Exception:
        s.rollback()
        return False
    finally:
        s.close()


def _to_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name,
            "password_hash": u.password_hash, "is_admin": bool(u.is_admin)}
