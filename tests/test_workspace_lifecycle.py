# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The extracted workspace-open orchestration (Phase 6).

``backend.workspace.lifecycle`` owns what ``apps/streamlit/app.py`` used to do
inline on workspace open: registry lookup → lazy provisioning → graph-client
creation — with every failure mode reported, never raised. Alongside it:
the container→host path translation (``backend.workspace.paths``) and the
unified metadata reader (``backend.workspace.metadata``) that both frontends
now share.

Everything runs against a tmp-dir registry (auto-discovery over USECASES_DIR)
with provisioning and the graph client mocked — no triplestore needed.
"""
from __future__ import annotations

import json
import types

import pytest

import backend.workspace.lifecycle as lifecycle
from backend.workspace import (
    check_connection,
    load_workspace_metadata,
    open_workspace,
    read_workspace_metadata,
    resolve_workspace_local_path,
    to_host_display_path,
)
from backend.workspace.paths import candidate_local_roots, native_local_path


WS_ID = "lifecycle-ws"


@pytest.fixture()
def registry_root(tmp_path, monkeypatch):
    """A tmp USECASES_DIR holding one auto-discoverable workspace."""
    ws = tmp_path / WS_ID
    (ws / "ontology" / "extensions").mkdir(parents=True)  # discovery signal
    meta_dir = ws / "workspace_meta"
    meta_dir.mkdir()
    (meta_dir / "metadata.json").write_text(json.dumps({
        "name": "Lifecycle WS", "type": "District", "location": "Zurich",
    }), encoding="utf-8")

    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    # Point the YAML registry at nothing so only tmp + bundled demo exist.
    monkeypatch.setenv("DIGICITIES_WORKSPACES_FILE", str(tmp_path / "none.yaml"))
    # Keep the on-disk state hermetic for path translation tests, and make
    # sure the legacy NextCloud fallback can't reach a real server.
    monkeypatch.delenv("USECASES_HOST_PATH", raising=False)
    monkeypatch.delenv("NEXTCLOUD_BASIC_USERNAME", raising=False)
    monkeypatch.delenv("NEXTCLOUD_BASIC_PASSWORD", raising=False)
    return tmp_path


class FakeClient:
    """Stands in for GraphDBClient; records how it was built."""

    def __init__(self, token=None, selected_repo=None, status_code=200, raises=False):
        self.token = token
        self.selected_repo = selected_repo
        self._status = status_code
        self._raises = raises

    def sparql_api_query(self, query, out_format="response"):
        if self._raises:
            raise ConnectionError("store down")
        return types.SimpleNamespace(status_code=self._status)


# ---------------------------------------------------------------------------
# open_workspace — the flow the Streamlit shell parks in session state
# ---------------------------------------------------------------------------

def test_open_workspace_happy_path(registry_root, monkeypatch):
    provisioned = {}

    def fake_provision(ctx):
        provisioned["ctx"] = ctx
        return True

    monkeypatch.setattr(lifecycle, "ensure_workspace_repo", fake_provision)
    opened = open_workspace(WS_ID, token="tok", client_factory=FakeClient)

    assert opened.ctx is not None and opened.ctx.id == WS_ID
    assert opened.ctx.name == "Lifecycle WS"  # metadata-derived registry name
    assert provisioned["ctx"] is opened.ctx
    assert opened.provisioned and opened.provision_error is None
    assert opened.graphdb_repository == WS_ID
    assert isinstance(opened.client, FakeClient)
    assert opened.client.token == "tok"
    assert opened.client.selected_repo == WS_ID
    assert opened.connected and opened.client_error is None


def test_open_workspace_unknown_id_still_builds_client(registry_root, monkeypatch):
    """Pre-registry ids (e.g. Keycloak groups) fall back to id-as-repo."""
    monkeypatch.setattr(lifecycle, "ensure_workspace_repo",
                        lambda ctx: pytest.fail("must not provision without a ctx"))
    opened = open_workspace("not-in-registry", token="tok", client_factory=FakeClient)

    assert opened.ctx is None
    assert not opened.provisioned and opened.provision_error is None
    assert opened.graphdb_repository == "not-in-registry"
    assert opened.client.selected_repo == "not-in-registry"


def test_open_workspace_provisioning_failure_is_nonfatal(registry_root, monkeypatch):
    def boom(ctx):
        raise RuntimeError("triplestore unreachable")

    monkeypatch.setattr(lifecycle, "ensure_workspace_repo", boom)
    opened = open_workspace(WS_ID, token="tok", client_factory=FakeClient)

    assert opened.provision_error == "triplestore unreachable"
    assert not opened.provisioned
    # The client is still built — file-based modules keep working.
    assert opened.client is not None and opened.connected


def test_open_workspace_client_failure_reported_not_raised(registry_root, monkeypatch):
    monkeypatch.setattr(lifecycle, "ensure_workspace_repo", lambda ctx: True)

    def bad_factory(**kwargs):
        raise ValueError("no route to store")

    opened = open_workspace(WS_ID, token="tok", client_factory=bad_factory)
    assert opened.client is None and not opened.connected
    assert opened.client_error == "no route to store"


def test_open_workspace_provision_flag_skips_provisioning(registry_root, monkeypatch):
    monkeypatch.setattr(lifecycle, "ensure_workspace_repo",
                        lambda ctx: pytest.fail("provision=False must skip"))
    opened = open_workspace(WS_ID, client_factory=FakeClient, provision=False)
    assert opened.ctx is not None and not opened.provisioned


def test_open_workspace_registry_error_degrades_to_id(registry_root, monkeypatch):
    def broken_registry():
        raise RuntimeError("yaml exploded")

    monkeypatch.setattr(lifecycle, "load_registry", broken_registry)
    opened = open_workspace(WS_ID, client_factory=FakeClient)
    assert opened.ctx is None
    assert opened.graphdb_repository == WS_ID
    assert opened.client is not None


# ---------------------------------------------------------------------------
# connection check — status only, never raises
# ---------------------------------------------------------------------------

def test_check_connection_ok():
    assert check_connection(FakeClient(status_code=200)) is True


def test_check_connection_bad_status():
    assert check_connection(FakeClient(status_code=503)) is False


def test_check_connection_transport_error():
    assert check_connection(FakeClient(raises=True)) is False


def test_check_connection_no_client():
    assert check_connection(None) is False


# ---------------------------------------------------------------------------
# container → host path translation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host_root,ws_dir,path,expected", [
    # Windows host root renders with backslashes, ready for File Explorer.
    ("C:/Users/me/usecases", "/app/data/usecases",
     "/app/data/usecases/foo", "C:\\Users\\me\\usecases\\foo"),
    ("C:/Users/me/usecases", "/app/data/usecases",
     "/app/data/usecases", "C:\\Users\\me\\usecases"),
    # POSIX host root keeps forward slashes.
    ("/home/me/usecases", "/app/data/usecases",
     "/app/data/usecases/foo/bar", "/home/me/usecases/foo/bar"),
    # Not under the mount → None (already a real host path).
    ("/home/me/usecases", "/app/data/usecases", "/somewhere/else", None),
    # Prefix must match on a path boundary, not as a substring.
    ("/home/me/usecases", "/app/data/usecases",
     "/app/data/usecases-other/foo", None),
])
def test_to_host_display_path_table(monkeypatch, host_root, ws_dir, path, expected):
    monkeypatch.setenv("USECASES_HOST_PATH", host_root)
    monkeypatch.setenv("USECASES_DIR", ws_dir)
    assert to_host_display_path(path) == expected


def test_to_host_display_path_requires_both_env(monkeypatch):
    monkeypatch.delenv("USECASES_HOST_PATH", raising=False)
    monkeypatch.setenv("USECASES_DIR", "/app/data/usecases")
    assert to_host_display_path("/app/data/usecases/foo") is None


def test_candidate_local_roots_env_first_and_deduped(monkeypatch):
    from backend.workspace.registry import DEFAULT_USECASES_DIR
    monkeypatch.setenv("USECASES_DIR", str(DEFAULT_USECASES_DIR))
    roots = candidate_local_roots()
    # env dir equals the default → deduped, and stays first.
    assert roots[0] == str(DEFAULT_USECASES_DIR)
    assert len(roots) == len({__import__("os").path.normpath(r) for r in roots})


def test_native_local_path_only_for_file_backends(registry_root):
    from backend.workspace import load_registry
    ctx = load_registry().by_id(WS_ID)
    assert native_local_path(ctx) == str(registry_root / WS_ID)
    assert native_local_path(None) is None
    nonlocal_ctx = types.SimpleNamespace(storage=types.SimpleNamespace(
        protocol="webdav", root="ws"))
    assert native_local_path(nonlocal_ctx) is None


def test_resolve_workspace_local_path_via_registry(registry_root):
    assert resolve_workspace_local_path(WS_ID) == str(registry_root / WS_ID)


def test_resolve_workspace_local_path_translates_to_host(registry_root, monkeypatch):
    monkeypatch.setenv("USECASES_HOST_PATH", "/host/usecases")
    # The registry resolves paths; the display translation maps them to the
    # host side of the bind mount.
    resolved = str(registry_root / WS_ID).replace("\\", "/")
    monkeypatch.setenv("USECASES_DIR", str(registry_root))
    assert resolve_workspace_local_path(WS_ID) == f"/host/usecases/{WS_ID}"
    assert to_host_display_path(resolved) == f"/host/usecases/{WS_ID}"


def test_resolve_workspace_local_path_unknown_id(registry_root):
    assert resolve_workspace_local_path("nope") is None


def test_resolve_prefers_caller_context(registry_root, tmp_path):
    """A live WorkspaceContext (session state) wins over the registry scan."""
    from backend.workspace import WorkspaceStorage
    other_root = tmp_path / "elsewhere" / WS_ID
    other_root.mkdir(parents=True)
    ctx = types.SimpleNamespace(id=WS_ID,
                                storage=WorkspaceStorage.local(str(other_root)))
    assert resolve_workspace_local_path(WS_ID, ctx=ctx) == str(other_root)
    # A ctx for a *different* workspace is ignored.
    ctx_other = types.SimpleNamespace(id="different",
                                      storage=WorkspaceStorage.local(str(other_root)))
    assert resolve_workspace_local_path(WS_ID, ctx=ctx_other) == str(registry_root / WS_ID)


# ---------------------------------------------------------------------------
# unified metadata reader — one function behind Streamlit + the REST API
# ---------------------------------------------------------------------------

def test_load_workspace_metadata_by_id(registry_root):
    meta = load_workspace_metadata(WS_ID)
    assert meta["type"] == "District" and meta["location"] == "Zurich"


def test_load_workspace_metadata_unknown_id_empty(registry_root):
    assert load_workspace_metadata("nope") == {}


def test_read_workspace_metadata_missing_file(registry_root, tmp_path):
    from backend.workspace import WorkspaceStorage
    bare = tmp_path / "bare"
    bare.mkdir()
    ctx = types.SimpleNamespace(storage=WorkspaceStorage.local(str(bare)))
    assert read_workspace_metadata(ctx) == {}
    assert read_workspace_metadata(None) == {}


def test_read_workspace_metadata_rejects_non_dict_and_bad_json(tmp_path):
    from backend.workspace import WorkspaceStorage
    ws = tmp_path / "badmeta"
    (ws / "workspace_meta").mkdir(parents=True)
    ctx = types.SimpleNamespace(storage=WorkspaceStorage.local(str(ws)))

    (ws / "workspace_meta" / "metadata.json").write_text('["a", "list"]', encoding="utf-8")
    assert read_workspace_metadata(ctx) == {}

    (ws / "workspace_meta" / "metadata.json").write_text("{not json", encoding="utf-8")
    assert read_workspace_metadata(ctx) == {}


def test_api_workspace_info_uses_unified_reader(registry_root, api_client, monkeypatch):
    """The REST API reads the same metadata.json through the same function."""
    r = api_client.get(f"/api/workspaces/{WS_ID}/info")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "District"
    assert body["location"] == "Zurich"
    assert body["name"] == "Lifecycle WS"
