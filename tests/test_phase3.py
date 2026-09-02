# SPDX-License-Identifier: Apache-2.0
"""Phase 3: Alembic schema management + admin seeding. Temp SQLite; no Postgres."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("bcrypt")


def test_ensure_schema_creates_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    import backend.db.session as S
    S._engine.cache_clear(); S._sessionmaker.cache_clear()
    from backend.db.migrate import ensure_schema
    ensure_schema()
    from sqlalchemy import inspect
    t = set(inspect(S.engine()).get_table_names())
    assert {"users", "workspaces", "workspace_acl", "alembic_version"} <= t


def test_ensure_schema_noop_when_db_disabled(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import backend.db.session as S
    S._engine.cache_clear(); S._sessionmaker.cache_clear()
    from backend.db.migrate import ensure_schema
    ensure_schema()                              # must not raise


def test_bootstrap_seeds_admin_idempotently(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@demo.io")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass123")
    import backend.db.session as S
    S._engine.cache_clear(); S._sessionmaker.cache_clear()
    from backend.db.migrate import ensure_schema
    from apps.api.auth_local import bootstrap
    from backend.db import users_repo
    ensure_schema()
    bootstrap(); bootstrap()                     # idempotent
    u = users_repo.get_by_email("admin@demo.io")
    assert u and u["display_name"] == "Admin"
    from apps.api.auth_local import verify_password
    assert verify_password("adminpass123", u["password_hash"])
