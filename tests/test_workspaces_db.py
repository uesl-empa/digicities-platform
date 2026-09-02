# SPDX-License-Identifier: Apache-2.0
"""Phase-1 workspace metadata DB + registry cache. The DB is optional (no DATABASE_URL
=> no-op); tests use a temp SQLite file so no Postgres is needed."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")


def _reset_engine_cache():
    import backend.db.session as S
    S._engine.cache_clear()
    S._sessionmaker.cache_clear()


def test_repo_upsert_list_get(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    _reset_engine_cache()
    from backend.db import workspaces_repo as R
    R.init_db()
    R.upsert({"id": "w1", "name": "W1", "graphdb_repo": "w1",
              "description": "d", "tags": ["demo"], "protected": True})
    R.upsert({"id": "w1", "name": "W1 renamed", "protected": True})   # update, keep visibility
    rows = {r["id"]: r for r in R.list_all()}
    assert rows["w1"]["name"] == "W1 renamed"
    assert rows["w1"]["visibility"] == "shared"          # default on create, not overwritten
    assert rows["w1"]["tags"] == []                      # last upsert carried no tags
    assert R.get("w1")["name"] == "W1 renamed"
    assert R.get("nope") is None


def test_db_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _reset_engine_cache()
    import backend.db.session as S
    from backend.db import workspaces_repo as R
    assert S.db_enabled() is False
    R.init_db()                                          # no-op
    R.upsert({"id": "x", "name": "X"})                   # no-op, no error
    assert R.list_all() == []
    assert R.get("x") is None


def test_registry_cache_reads_and_falls_back(monkeypatch):
    import apps.api.registry_cache as RC

    class _Ctx:
        def __init__(self, i):
            self.id = i; self.name = i.upper(); self.graphdb_repository = i
            self.description = ""; self.tags = []; self.storage = None

    class _Reg(list):
        def by_id(self, i):
            return next((c for c in self if c.id == i), None)

    monkeypatch.setattr(RC, "load_registry", lambda: _Reg([_Ctx("a"), _Ctx("b")]))
    RC._loaded = False; RC._by_id = {}; RC._contexts = []

    assert RC.by_id("a").name == "A"                     # from the cache
    assert {c.id for c in RC.all_contexts()} == {"a", "b"}
    assert RC.by_id("zzz") is None                       # miss → registry fallback → None
