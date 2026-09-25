# SPDX-License-Identifier: Apache-2.0
"""Engine + session, built lazily from ``DATABASE_URL``. None when unset (DB disabled)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


def database_url() -> Optional[str]:
    """``DATABASE_URL`` with the Postgres driver named explicitly.

    A bare ``postgresql://`` lets SQLAlchemy pick the driver, and 2.1 changed
    that default from psycopg2 to psycopg (v3). The image ships psycopg2
    (apps/api/requirements.txt), so a rebuild that resolved SQLAlchemy 2.1
    failed every database call — sign-in and the workspace list — with
    ``No module named 'psycopg'`` (live, 2026-09-25). A URL that already names
    a driver (``postgresql+...://``) is left as it is."""
    url = os.getenv("DATABASE_URL") or None
    if url and url.startswith(("postgresql://", "postgres://")):
        url = "postgresql+psycopg2://" + url.split("://", 1)[1]
    return url


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
