# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Live NextCloud verification — the SAME suite before and after deployment.

Runs the storage + mirror + discovery lifecycle against a REAL NextCloud over
real WebDAV. Point it anywhere:

  # 1. PRE-DEPLOY, on Docker Desktop against the deploy overlay:
  #    docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d
  NEXTCLOUD_LIVE_URL=http://localhost:8080 \
  NEXTCLOUD_LIVE_USER=admin NEXTCLOUD_LIVE_PASSWORD=<pw> \
      pytest -m live tests/test_nextcloud_live.py -v

  # 2. POST-DEPLOY, against the cloud instance (same command, real URL):
  NEXTCLOUD_LIVE_URL=https://files.your-deployment.example \
  NEXTCLOUD_LIVE_USER=... NEXTCLOUD_LIVE_PASSWORD=... \
      pytest -m live tests/test_nextcloud_live.py -v

(PowerShell: `$env:NEXTCLOUD_LIVE_URL = "..."` etc., then the pytest line.)

Skipped (not failed) when NEXTCLOUD_LIVE_URL is unset, and deselected from
normal runs by the `live` marker — CI runs it in the dedicated
`nextcloud-live` workflow with a service container. Everything happens in a
throwaway `workspace_livecheck` folder that is created and torn down here;
nothing else on the server is touched.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.live

URL = os.environ.get("NEXTCLOUD_LIVE_URL", "")
USER = os.environ.get("NEXTCLOUD_LIVE_USER") \
    or os.environ.get("NEXTCLOUD_BASIC_USERNAME", "admin")
PASSWORD = os.environ.get("NEXTCLOUD_LIVE_PASSWORD") \
    or os.environ.get("NEXTCLOUD_BASIC_PASSWORD", "")

if not URL:
    pytest.skip("set NEXTCLOUD_LIVE_URL (+_USER/_PASSWORD) to run the live "
                "NextCloud verification", allow_module_level=True)

WS = "workspace_livecheck"
DAV = f"{URL.rstrip('/')}/remote.php/dav/files/{USER}"


@pytest.fixture(scope="module")
def storage():
    from backend.workspace.storage import WorkspaceStorage
    s = WorkspaceStorage.webdav(DAV, USER, PASSWORD, WS)
    # fresh start AND teardown: nothing survives a run
    try:
        s.fs.rm(s.root, recursive=True)
    except Exception:
        pass
    s.mkdir("")
    yield s
    try:
        s.fs.rm(s.root, recursive=True)
    except Exception:
        pass


@pytest.fixture()
def ctx(storage, tmp_path, monkeypatch):
    from backend.workspace import mirror
    monkeypatch.setenv("USECASES_DIR", str(tmp_path / "usecases"))
    mirror._last_pull.clear()
    return SimpleNamespace(id=WS, storage=storage)


def test_webdav_lifecycle(storage):
    """The raw op surface against the real server — mkdir (MKCOL trailing
    slash + trusted_domains proven working), write/read/glob/walk/delete."""
    storage.mkdir("ingestion/output")
    storage.write_text("ingestion/output/ws.ttl", "@prefix : <urn:x> . :a :b :c .")
    storage.write_bytes("scenarios/baseline.ttl", "scénario".encode("utf-8"))
    assert storage.exists("ingestion/output/ws.ttl")
    assert storage.read_text("ingestion/output/ws.ttl").startswith("@prefix")
    assert storage.read_bytes("scenarios/baseline.ttl").decode("utf-8") == "scénario"
    assert storage.glob("ingestion/output/*.ttl") == ["ingestion/output/ws.ttl"]
    assert set(storage.walk_files()) >= {"ingestion/output/ws.ttl",
                                         "scenarios/baseline.ttl"}
    storage.delete("scenarios/baseline.ttl")
    assert not storage.exists("scenarios/baseline.ttl")


def test_mirror_cycle_against_real_server(ctx):
    from backend.workspace import mirror

    local = mirror.local_root(ctx)
    (local / "services").mkdir(parents=True, exist_ok=True)
    (local / "services" / "Svc.ttl").write_text("svc v1", encoding="utf-8")
    r = mirror.push(ctx)
    assert "services/Svc.ttl" in r["pushed"]
    assert ctx.storage.read_text("services/Svc.ttl") == "svc v1"

    # a user edit made directly in NextCloud reaches the working copy
    # (membership, not equality: earlier lifecycle files may ride along)
    ctx.storage.write_text("services/Svc.ttl", "svc v2 — edited in nextcloud")
    r = mirror.pull(ctx, force=True)
    assert "services/Svc.ttl" in r["pulled"]
    assert "edited in nextcloud" in (local / "services" / "Svc.ttl") \
        .read_text(encoding="utf-8")

    # a local deletion (reset workspace) reaches the durable store
    (local / "services" / "Svc.ttl").unlink()
    r = mirror.push(ctx)
    assert r["deleted"] == ["services/Svc.ttl"]
    assert not ctx.storage.exists("services/Svc.ttl")

    # secrets never leave the server
    (local / ".agent-keys.json").write_text("{}", encoding="utf-8")
    mirror.push(ctx)
    assert not ctx.storage.exists(".agent-keys.json")


def test_workspace_autodiscovery(storage, monkeypatch):
    """A folder with workspace_meta/metadata.json is a workspace — the
    registry must find it on this server without any local YAML entry."""
    from backend.workspace import registry

    storage.write_text("workspace_meta/metadata.json",
                       '{"name": "Live check", "description": "throwaway"}')
    monkeypatch.setenv("NEXTCLOUD_BASE_URL", URL)
    monkeypatch.setenv("NEXTCLOUD_BASIC_USERNAME", USER)
    monkeypatch.setenv("NEXTCLOUD_BASIC_PASSWORD", PASSWORD)
    registry.clear_nextcloud_discovery_cache()
    found = {c.id: c for c in registry._autodiscover_nextcloud_workspaces()}
    assert WS in found
    assert found[WS].name == "Live check"
    assert found[WS].storage.protocol == "webdav"
    registry.clear_nextcloud_discovery_cache()


def test_pull_throttle_is_real(ctx):
    from backend.workspace import mirror
    t0 = time.perf_counter()
    mirror.pull(ctx, force=True)
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    r = mirror.pull(ctx)                       # inside the TTL window
    assert r["skipped"] is True
    assert time.perf_counter() - t0 < first + 0.05   # throttled call ~free


def test_api_serves_a_nextcloud_workspace_when_available():
    """OPTIONAL end-to-end: with DIGICITIES_API_URL set (post-deploy check),
    the REST files listing must answer for a NextCloud-discovered workspace —
    proving get_ctx → mirror.pull → ws_root works through the whole stack."""
    api = os.environ.get("DIGICITIES_API_URL", "")
    if not api:
        pytest.skip("set DIGICITIES_API_URL for the end-to-end API check")
    import requests
    r = requests.get(f"{api.rstrip('/')}/api/workspaces/{WS}/files",
                     params={"path": ""}, timeout=30)
    assert r.status_code == 200, r.text
    assert "entries" in r.json()
