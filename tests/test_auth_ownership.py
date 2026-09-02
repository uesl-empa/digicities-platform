# SPDX-License-Identifier: Apache-2.0
"""Phase-2 accounts + ownership/visibility. DB-backed (temp SQLite); no Postgres needed."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("bcrypt")
pytest.importorskip("jwt")


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    import backend.db.session as S
    S._engine.cache_clear()
    S._sessionmaker.cache_clear()
    from backend.db import workspaces_repo as W
    W.init_db()
    return W


def test_password_hash_roundtrip():
    from apps.api.auth_local import hash_password, verify_password
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    from apps.api.auth_local import make_token, _decode
    assert _decode(make_token("u1")) == "u1"
    assert _decode("not-a-token") is None


def test_ownership_visibility_and_acl(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from backend.db import users_repo, workspaces_repo
    from apps.api.auth_local import hash_password

    alice = users_repo.create_user("a@x.io", hash_password("password1"))
    bob = users_repo.create_user("b@x.io", hash_password("password1"))
    assert users_repo.get_by_email("a@x.io")["id"] == alice["id"]

    workspaces_repo.upsert({"id": "legacy", "name": "L", "graphdb_repo": "legacy"})   # unowned → shared
    workspaces_repo.set_owner("alicepriv", alice["id"], "private")
    workspaces_repo.set_owner("aliceshared", alice["id"], "shared")

    va = workspaces_repo.visible_to(alice["id"])
    vb = workspaces_repo.visible_to(bob["id"])
    anon = workspaces_repo.visible_to(None)
    assert {"legacy", "alicepriv", "aliceshared"} <= va
    assert "alicepriv" not in vb and {"legacy", "aliceshared"} <= vb    # private hidden from bob
    assert "alicepriv" not in anon and {"legacy", "aliceshared"} <= anon  # and from anonymous

    assert workspaces_repo.can_edit("alicepriv", alice["id"])          # owner
    assert not workspaces_repo.can_edit("alicepriv", bob["id"])        # not owner/editor
    assert not workspaces_repo.can_edit("alicepriv", None)             # owned + anonymous → no
    assert workspaces_repo.can_edit("legacy", bob["id"])               # unowned legacy = editable
    assert workspaces_repo.can_edit("legacy", None)                    # unowned + anon = editable

    workspaces_repo.grant_editor("alicepriv", bob["id"])               # share as editor
    assert workspaces_repo.can_edit("alicepriv", bob["id"])
    assert "alicepriv" in workspaces_repo.visible_to(bob["id"])        # acl also grants visibility


def test_db_disabled_is_open(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import backend.db.session as S
    S._engine.cache_clear()
    S._sessionmaker.cache_clear()
    from backend.db import workspaces_repo
    assert workspaces_repo.visible_to("u") is None      # None = no filter (auth off)
    assert workspaces_repo.can_edit("w", "u") is True
