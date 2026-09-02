# SPDX-License-Identifier: Apache-2.0
"""ORM models. Phase 1: the ``workspaces`` catalog. Phase 2 adds ``users`` + ``workspace_acl``."""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)   # folder / graph id
    name: Mapped[str] = mapped_column(String(512), default="")
    owner_id: Mapped[str | None] = mapped_column(String(255), default=None)   # phase 2
    visibility: Mapped[str] = mapped_column(String(16), default="shared")     # 'private' | 'shared'
    backend: Mapped[str] = mapped_column(String(32), default="local")         # local | nextcloud | fsspec
    graphdb_repo: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")                     # json array
    protected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
