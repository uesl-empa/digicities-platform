# SPDX-License-Identifier: Apache-2.0
"""Engine + session, built lazily from ``DATABASE_URL``. None when unset (DB disabled)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


def database_url() -> Optional[str]:
    return os.getenv("DATABASE_URL") or None


@lru_cache(maxsize=1)
def _engine():
    url = database_url()
    if not url:
        return None
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True, future=True)


def engine():
    return _engine()


@lru_cache(maxsize=1)
def _sessionmaker():
    eng = _engine()
    if eng is None:
        return None
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=eng, future=True, expire_on_commit=False)


def session():
    """A new Session, or None when no ``DATABASE_URL`` is configured."""
    sm = _sessionmaker()
    return sm() if sm else None


def db_enabled() -> bool:
    return _engine() is not None
