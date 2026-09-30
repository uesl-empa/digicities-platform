# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Where workspaces live is decided once per installation.

The live bug this pins: with NextCloud storage the server keeps a working copy
of each workspace under USECASES_DIR; local auto-discovery registered that copy
as a LOCAL workspace as soon as the agent wrote its first build folder, and from
then on the workspace's changes silently stopped reaching NextCloud (five live
workspaces, 2026-09-30).
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import fsspec
import pytest

from backend.workspace import mirror
from backend.workspace import registry as reg
from backend.workspace.storage import WorkspaceStorage
from backend.workspace.storage_mode import describe_storage, storage_backend


def _remote_ctx(ws_id, root):
    storage = WorkspaceStorage(fsspec.filesystem("file"), str(root).replace("\\", "/"), "webdav")
    return SimpleNamespace(id=ws_id, name=ws_id, storage=storage, graphdb_repository=ws_id,
                           description="", tags=[])


@pytest.fixture()
def usecases(tmp_path, monkeypatch):
    base = tmp_path / "usecases"
    # the working copy of a NextCloud workspace, after the agent's first build
    (base / "workspace_traffic" / "ingestion" / "output").mkdir(parents=True)
    # a folder that exists only locally
    (base / "workspace_localonly" / "scenarios").mkdir(parents=True)
    monkeypatch.setenv("USECASES_DIR", str(base))
    monkeypatch.setattr(reg, "_usecases_dir", lambda: base)
    monkeypatch.setattr(reg, "_registry_path", lambda: None)
    remote = tmp_path / "remote" / "workspace_traffic"
    remote.mkdir(parents=True)
    monkeypatch.setattr(reg, "_autodiscover_nextcloud_workspaces",
                        lambda: [_remote_ctx("workspace_traffic", remote)])
    return base


def _by_id(r, ws_id):
    return next((c for c in r.contexts if c.id == ws_id), None)


def test_with_nextcloud_a_working_copy_is_never_a_local_workspace(usecases, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "nextcloud")
    r = reg.load_registry()
    traffic = _by_id(r, "workspace_traffic")
    assert traffic is not None and traffic.storage.protocol == "webdav"   # NextCloud wins
    assert mirror.enabled(traffic)                                       # so it syncs
    assert _by_id(r, "workspace_localonly") is None                      # not a workspace


def test_local_testing_finds_the_local_folders_only(usecases, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    r = reg.load_registry()
    assert _by_id(r, "workspace_localonly").storage.protocol == "file"
    assert _by_id(r, "workspace_traffic").storage.protocol == "file"      # its local folder


def test_the_setting_defaults_to_local(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    assert storage_backend() == "local"
    monkeypatch.setenv("STORAGE_BACKEND", " NextCloud ")
    assert storage_backend() == "nextcloud"


def test_describe_storage_shows_the_folder_on_your_drive_or_the_nextcloud_host(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("USECASES_DIR", "/app/data/usecases")
    monkeypatch.setenv("USECASES_HOST_PATH", "C:/Users/me/workspaces")
    d = describe_storage()
    assert d == {"backend": "local", "label": "This computer",
                 "location": "C:\\Users\\me\\workspaces"}
    monkeypatch.setenv("STORAGE_BACKEND", "nextcloud")
    monkeypatch.setenv("NEXTCLOUD_BASE_URL", "https://nc.example.org/nextcloud")
    monkeypatch.setenv("NEXTCLOUD_BASIC_PASSWORD", "secret")
    d = describe_storage()
    assert d == {"backend": "nextcloud", "label": "NextCloud", "location": "nc.example.org"}
    assert "secret" not in str(d)


def test_create_follows_the_installation(tmp_path, monkeypatch):
    from backend.workspace import creation
    monkeypatch.setattr(creation, "_usecases_dir", lambda: tmp_path)
    monkeypatch.setattr(creation, "workspace_id_exists", lambda ws_id: False)
    made = {}

    def _webdav(base, user, pw, root):
        made["root"] = root
        return WorkspaceStorage.local(str(tmp_path / "nc" / root))

    monkeypatch.setattr(creation.WorkspaceStorage, "webdav", staticmethod(_webdav))
    monkeypatch.setenv("NEXTCLOUD_BASE_URL", "http://nc")
    monkeypatch.setenv("NEXTCLOUD_BASIC_USERNAME", "u")
    monkeypatch.setenv("NEXTCLOUD_BASIC_PASSWORD", "p")
    monkeypatch.setenv("STORAGE_BACKEND", "nextcloud")
    ctx = creation.create_workspace("Traffic Test", provision_graph=False)
    assert ctx.id == "workspace_traffic_test" and made["root"] == "workspace_traffic_test"
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    ctx = creation.create_workspace("Local Test", provision_graph=False)
    assert ctx.storage.protocol == "file" and (tmp_path / ctx.id).is_dir()


# ── the copy to NextCloud ────────────────────────────────────────────────────
@pytest.fixture()
def mirrored(tmp_path, monkeypatch):
    base = tmp_path / "usecases"
    monkeypatch.setenv("USECASES_DIR", str(base))
    ctxs = []
    for ws in ("ws1", "ws2"):
        (tmp_path / "remote" / ws).mkdir(parents=True)
        ctxs.append(_remote_ctx(ws, tmp_path / "remote" / ws))
    return base, ctxs


def _w(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_startup_catch_up_publishes_every_pending_change(mirrored, tmp_path):
    base, ctxs = mirrored
    _w(base / "ws1" / "workspace_meta" / "onboarding_chats" / "chat-1.json", "{}")
    _w(base / "ws2" / "scenarios" / "baseline.ttl", "s")
    local_only = SimpleNamespace(id="demo", storage=WorkspaceStorage.local(str(tmp_path / "d")))
    out = mirror.push_all(ctxs + [local_only])
    assert out == {"ws1": 1, "ws2": 1}                       # local workspaces are left alone
    assert (tmp_path / "remote" / "ws1" / "workspace_meta" / "onboarding_chats"
            / "chat-1.json").exists()
    assert mirror.push_all(ctxs) == {"ws1": 0, "ws2": 0}     # nothing pending → nothing sent


def test_pushes_of_one_workspace_take_turns(mirrored, monkeypatch):
    """Overlapping pushes each load, upload and save the manifest — the later
    save dropping the other's entries. One push at a time per workspace."""
    base, (ctx, _) = mirrored
    for i in range(6):
        _w(base / "ws1" / "scenarios" / f"s{i}.ttl", f"scenario {i}")
    inside, peak = [0], [0]
    real = ctx.storage.write_bytes

    def slow_write(rel, data):
        inside[0] += 1
        peak[0] = max(peak[0], inside[0])
        time.sleep(0.01)
        real(rel, data)
        inside[0] -= 1

    monkeypatch.setattr(ctx.storage, "write_bytes", slow_write)
    ts = [threading.Thread(target=mirror.push, args=(ctx,)) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1
    manifest = mirror._load_manifest(base / "ws1")
    assert {f"scenarios/s{i}.ttl" for i in range(6)} <= set(manifest)


# ── REST ─────────────────────────────────────────────────────────────────────
@pytest.mark.api
def test_rest_storage_endpoint_and_workspace_storage_field(api_client, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "nextcloud")
    monkeypatch.setenv("NEXTCLOUD_BASE_URL", "https://nc.example.org")
    r = api_client.get("/api/storage")
    assert r.status_code == 200 and r.json()["backend"] == "nextcloud"
    ws = api_client.get("/api/workspaces").json()
    assert ws and all(w.get("storage") in ("nextcloud", "local", "bundled") for w in ws)
