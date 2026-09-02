# SPDX-License-Identifier: Apache-2.0
"""User accounts repository. No-op / None when the DB is disabled (no DATABASE_URL)."""
from __future__ import annotations

import uuid
from typing import Optional

from .models import User
from .session import session


def create_user(email: str, password_hash: str, display_name: str = "") -> Optional[dict]:
    s = session()
    if s is None:
        return None
    try:
        uid = uuid.uuid4().hex
        s.add(User(id=uid, email=email.strip().lower(), password_hash=password_hash,
                   display_name=display_name or email.split("@")[0]))
        s.commit()
        return {"id": uid, "email": email.strip().lower(), "display_name": display_name}
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


def _to_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name,
            "password_hash": u.password_hash}
