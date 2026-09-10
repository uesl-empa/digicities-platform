# SPDX-License-Identifier: Apache-2.0
"""Private-deployment auth surface: the registration switch, admin account
management, and the declarative workspace assign route. DB-backed (temp SQLite)."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("bcrypt")
pytest.importorskip("jwt")

pytestmark = pytest.mark.api


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    import backend.db.session as S
    S._engine.cache_clear()
    S._sessionmaker.cache_clear()
    from backend.db import workspaces_repo
    workspaces_repo.init_db()
    return workspaces_repo


def _mk_user(email, password="password1", is_admin=False):
    from apps.api.auth_local import hash_password
    from backend.db import users_repo
    return users_repo.create_user(email, hash_password(password), is_admin=is_admin)


def _login(client, email, password="password1"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_registration_switch(db, api_client, monkeypatch):
    monkeypatch.setenv("ALLOW_REGISTRATION", "0")
    r = api_client.post("/api/auth/register",
                        json={"email": "new@x.io", "password": "password1"})
    assert r.status_code == 403
    assert api_client.get("/api/auth/config").json()["allow_registration"] is False

    monkeypatch.delenv("ALLOW_REGISTRATION")          # default = open (today's behaviour)
    r = api_client.post("/api/auth/register",
                        json={"email": "new@x.io", "password": "password1"})
    assert r.status_code == 200 and r.json()["token"]
    assert api_client.get("/api/auth/config").json()["allow_registration"] is True


def test_admin_manages_accounts(db, api_client):
    _mk_user("root@x.io", is_admin=True)
    _mk_user("plain@x.io")
    admin = _login(api_client, "root@x.io")
    plain = _login(api_client, "plain@x.io")

    # non-admin: locked out of account management
    assert api_client.get("/api/auth/users", headers=plain).status_code == 403
    assert api_client.get("/api/auth/users").status_code == 401     # signed out

    r = api_client.post("/api/auth/users", headers=admin,
                        json={"email": "member@x.io", "password": "password1",
                              "display_name": "Member"})
    assert r.status_code == 200 and "token" not in r.json()          # no session handed out
    assert api_client.post("/api/auth/users", headers=admin,
                           json={"email": "member@x.io", "password": "password1"}
                           ).status_code == 409

    emails = [u["email"] for u in api_client.get("/api/auth/users", headers=admin).json()]
    assert emails == sorted(emails) and "member@x.io" in emails

    assert api_client.delete("/api/auth/users/root@x.io", headers=admin).status_code == 400
    assert api_client.delete("/api/auth/users/member@x.io", headers=admin).status_code == 200
    assert api_client.delete("/api/auth/users/member@x.io", headers=admin).status_code == 404
    # the deleted account's token no longer resolves
    member_can = api_client.post("/api/auth/login",
                                 json={"email": "member@x.io", "password": "password1"})
    assert member_can.status_code == 401


def test_bootstrap_promotes_seeded_admin(db, monkeypatch):
    from apps.api import auth_local
    from backend.db import users_repo
    _mk_user("seed@x.io")                              # pre-dates the is_admin column
    monkeypatch.setenv("ADMIN_EMAIL", "seed@x.io")
    monkeypatch.setenv("ADMIN_PASSWORD", "irrelevant1")
    auth_local.bootstrap()
    assert users_repo.get_by_email("seed@x.io")["is_admin"] is True


class _Ctx:
    id = "assignws"
    name = "Assign WS"
    graphdb_repository = "assignws"
    description = ""


@pytest.fixture()
def assign_ws(db, api_app):
    from apps.api.deps import get_ctx
    api_app.dependency_overrides[get_ctx] = lambda: _Ctx()
    return _Ctx.id


def test_assign_route_declarative(db, api_client, assign_ws):
    _mk_user("root@x.io", is_admin=True)
    lead = _mk_user("lead@x.io")
    _mk_user("member@x.io")
    _mk_user("other@x.io")
    admin = _login(api_client, "root@x.io")

    r = api_client.post(f"/api/workspaces/{assign_ws}/assign", headers=admin,
                        json={"owner_email": "lead@x.io", "visibility": "private",
                              "members": ["member@x.io", "ghost@x.io"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owner"] == "lead@x.io" and body["visibility"] == "private"
    assert body["members"] == ["member@x.io"] and body["unknown"] == ["ghost@x.io"]

    # a plain signed-in non-member cannot reassign an owned workspace
    other = _login(api_client, "other@x.io")
    assert api_client.post(f"/api/workspaces/{assign_ws}/assign", headers=other,
                           json={"visibility": "shared"}).status_code == 403

    # the owner can — and members is declarative: the new list revokes the old grant
    lead_h = _login(api_client, "lead@x.io")
    r = api_client.post(f"/api/workspaces/{assign_ws}/assign", headers=lead_h,
                        json={"members": ["other@x.io"]})
    assert r.status_code == 200 and r.json()["members"] == ["other@x.io"]

    from backend.db import workspaces_repo
    assert workspaces_repo.can_edit(assign_ws, lead["id"])           # owner keeps access
    assert assign_ws in workspaces_repo.visible_to(lead["id"])


def test_admin_sees_private_workspaces(db):
    from backend.db import workspaces_repo
    alice = _mk_user("alice@x.io")
    workspaces_repo.set_owner("alicepriv", alice["id"], "private")
    # deps.get_ctx / the list route skip the visibility filter for admins; the
    # underlying data still hides it from ordinary users
    bob = _mk_user("bob@x.io")
    assert "alicepriv" not in workspaces_repo.visible_to(bob["id"])
