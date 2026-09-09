# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The local↔remote workspace mirror (phase 2 of the NextCloud plan).

Both sides are real directories here — the "remote" is a WorkspaceStorage over
the local filesystem wearing a non-"file" protocol label, which is exactly the
surface the WebDAV backend exposes (walk_files/read/write/delete). What's
under test is the sync semantics: manifest-based change detection, deletion
propagation, the never-delete-unsynced-local-work rule, throttling, and the
hard no-op for local-fs workspaces.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import fsspec
import pytest

from backend.workspace import mirror
from backend.workspace.storage import WorkspaceStorage


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fake remote + a USECASES_DIR sandbox + a ctx wearing both."""
    remote_dir = tmp_path / "remote" / "ws1"
    remote_dir.mkdir(parents=True)
    local_base = tmp_path / "usecases"
    monkeypatch.setenv("USECASES_DIR", str(local_base))
    storage = WorkspaceStorage(fsspec.filesystem("file"),
                               str(remote_dir).replace("\\", "/"), "webdav")
    ctx = SimpleNamespace(id="ws1", storage=storage)
    mirror._last_pull.clear()
    return SimpleNamespace(ctx=ctx, remote=remote_dir,
                           local=local_base / "ws1")


def _w(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_local_fs_workspaces_are_hard_noops(tmp_path, monkeypatch):
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    ctx = SimpleNamespace(id="w", storage=WorkspaceStorage.local(str(tmp_path / "w")))
    assert not mirror.enabled(ctx)
    assert mirror.pull(ctx)["skipped"] is True
    assert mirror.push(ctx)["skipped"] is True


def test_push_uploads_new_and_changed_then_noops(env):
    _w(env.local / "ingestion" / "output" / "ws1.ttl", "replica v1")
    _w(env.local / "scenarios" / "baseline.ttl", "scenario")
    r = mirror.push(env.ctx)
    assert sorted(r["pushed"]) == ["ingestion/output/ws1.ttl", "scenarios/baseline.ttl"]
    assert (env.remote / "ingestion" / "output" / "ws1.ttl").read_text() == "replica v1"

    assert mirror.push(env.ctx)["pushed"] == []          # unchanged → no-op

    time.sleep(0.01)
    _w(env.local / "ingestion" / "output" / "ws1.ttl", "replica v2 — longer")
    r = mirror.push(env.ctx)
    assert r["pushed"] == ["ingestion/output/ws1.ttl"]
    assert (env.remote / "ingestion" / "output" / "ws1.ttl").read_text(encoding="utf-8") \
        == "replica v2 — longer"


def test_push_propagates_deletions_but_never_touches_unseen_remote_files(env):
    _w(env.local / "scenarios" / "old.ttl")
    mirror.push(env.ctx)
    _w(env.remote / "docs" / "written-in-nextcloud.md", "user's own file")

    (env.local / "scenarios" / "old.ttl").unlink()       # e.g. reset workspace
    r = mirror.push(env.ctx)
    assert r["deleted"] == ["scenarios/old.ttl"]
    assert not (env.remote / "scenarios" / "old.ttl").exists()
    # a file created directly in NextCloud that this mirror never saw survives
    assert (env.remote / "docs" / "written-in-nextcloud.md").exists()


def test_pull_downloads_new_files_and_throttles(env):
    _w(env.remote / "ingestion" / "input" / "ws1.xlsx", "workbook")
    r = mirror.pull(env.ctx)
    assert r["pulled"] == ["ingestion/input/ws1.xlsx"]
    assert (env.local / "ingestion" / "input" / "ws1.xlsx").read_text() == "workbook"

    _w(env.remote / "docs" / "late.md", "added after")
    assert mirror.pull(env.ctx)["skipped"] is True       # inside the TTL window
    r = mirror.pull(env.ctx, force=True)
    assert r["pulled"] == ["docs/late.md"]


def test_pull_sees_remote_edits_and_keeps_unpushed_local_work(env):
    _w(env.remote / "ingestion" / "input" / "ws1.xlsx", "v1")
    mirror.pull(env.ctx, force=True)
    # user edits the workbook in the NextCloud web UI (size changes)
    _w(env.remote / "ingestion" / "input" / "ws1.xlsx", "v2 edited in nextcloud")
    # meanwhile the server wrote something it hasn't pushed yet
    _w(env.local / "scenarios" / "fresh.ttl", "not yet pushed")

    r = mirror.pull(env.ctx, force=True)
    assert r["pulled"] == ["ingestion/input/ws1.xlsx"]
    assert (env.local / "ingestion" / "input" / "ws1.xlsx").read_text() \
        == "v2 edited in nextcloud"
    assert (env.local / "scenarios" / "fresh.ttl").exists()   # pull never deletes


def test_pull_mirrors_remote_deletion_of_synced_unchanged_files(env):
    _w(env.local / "services" / "Svc.ttl", "svc")
    mirror.push(env.ctx)
    (env.remote / "services" / "Svc.ttl").unlink()       # deleted on NextCloud

    r = mirror.pull(env.ctx, force=True)
    assert "-services/Svc.ttl" in r["pulled"]
    assert not (env.local / "services" / "Svc.ttl").exists()


def test_pull_never_deletes_locally_modified_files(env):
    _w(env.local / "services" / "Svc.ttl", "svc")
    mirror.push(env.ctx)
    (env.remote / "services" / "Svc.ttl").unlink()
    time.sleep(0.01)
    _w(env.local / "services" / "Svc.ttl", "svc — modified locally since")

    mirror.pull(env.ctx, force=True)
    assert (env.local / "services" / "Svc.ttl").exists()  # local edit wins
    # …and the next push re-publishes it
    r = mirror.push(env.ctx)
    assert "services/Svc.ttl" in r["pushed"]
    assert (env.remote / "services" / "Svc.ttl").exists()


def test_secrets_and_manifest_are_never_mirrored(env):
    _w(env.local / ".agent-keys.json", '{"anthropic": "sk-ant-…"}')
    _w(env.local / "scenarios" / "s.ttl")
    r = mirror.push(env.ctx)
    assert r["pushed"] == ["scenarios/s.ttl"]
    assert not (env.remote / ".agent-keys.json").exists()
    assert not (env.remote / mirror.MANIFEST_NAME).exists()

    _w(env.remote / ".agent-keys.json", "planted remotely")
    r = mirror.pull(env.ctx, force=True)
    assert r["pulled"] == []                              # excluded on pull too


def test_mirror_failures_are_soft(env, monkeypatch):
    _w(env.local / "scenarios" / "s.ttl")

    def _boom(*a, **k):
        raise ConnectionError("nextcloud down")
    monkeypatch.setattr(env.ctx.storage, "walk_files", _boom)
    assert "error" in mirror.pull(env.ctx, force=True)    # returned, not raised
    monkeypatch.setattr(env.ctx.storage, "write_bytes", _boom)
    assert "error" in mirror.push(env.ctx)
