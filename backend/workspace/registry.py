# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workspace registry — reads workspaces.yaml, returns WorkspaceContext objects.

Registry file location, in priority order:

1. `$DIGICITIES_WORKSPACES_FILE` env var, if set, pointing at a YAML file
2. `<repo_root>/data/workspaces.yaml`
3. Auto-discovery under `$USECASES_DIR` (default: `<repo_root>/data/usecases/`):
   every subdirectory with a populated `ontology/extensions/`, `scenarios/`,
   or `ingestion/output/` is treated as a local workspace named after the
   directory.

The auto-discovery path lets users drop a freshly-cloned usecase repo into
`data/usecases/` and have it appear in the workspace switcher without editing
config.

YAML schema:

    workspaces:
      - id: energy-simulation
        name: Energy Simulation (demo)
        backend: local
        path: /home/you/digicities-opensource/usecases/energy-simulation

      - id: vienna-school
        name: Vienna school retrofit
        backend: nextcloud
        nextcloud_root: vienna-school
        # Optional overrides; default to NEXTCLOUD_* env vars
        # nextcloud_base_url: https://my-nc.example.com/remote.php/dav/files/admin
        # nextcloud_username: admin
        # nextcloud_password: admin

      - id: alkmaar-windpark
        name: Alkmaar wind park
        backend: fsspec
        protocol: s3
        root: my-bucket/digicities-workspaces/alkmaar-windpark
        # Backend-specific options pass through as fsspec kwargs:
        # options:
        #   key: ...
        #   secret: ...
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

from .context import WorkspaceContext
from .storage import WorkspaceStorage


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "data" / "workspaces.yaml"
DEFAULT_USECASES_DIR = REPO_ROOT / "data" / "usecases"

# Bundled demo workspace(s): shipped in the repo (and image) so they are always
# offered, regardless of which usecases dir is mounted. Tagged "demo" so the UI
# can list them first and let the user hide them.
BUNDLED_DEMO_DIR = REPO_ROOT / "demo_workspaces"
BUNDLED_DEMO_IDS = ("energy-simulation",)


@dataclass
class WorkspaceRegistry:
    contexts: list[WorkspaceContext]

    def ids(self) -> list[str]:
        return [c.id for c in self.contexts]

    def by_id(self, workspace_id: str) -> Optional[WorkspaceContext]:
        for c in self.contexts:
            if c.id == workspace_id:
                return c
        return None

    def __iter__(self):
        return iter(self.contexts)

    def __len__(self) -> int:
        return len(self.contexts)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def _registry_path() -> Optional[Path]:
    env_path = os.environ.get("DIGICITIES_WORKSPACES_FILE")
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    return DEFAULT_REGISTRY if DEFAULT_REGISTRY.exists() else None


def _usecases_dir() -> Path:
    env_dir = os.environ.get("USECASES_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_USECASES_DIR


def _make_context_from_entry(entry: dict) -> WorkspaceContext:
    backend = entry.get("backend", "local").lower()
    ws_id = entry["id"]
    name = entry.get("name", ws_id)
    description = entry.get("description", "")
    tags = entry.get("tags", []) or []
    graphdb_repo = entry.get("graphdb_repository") or ws_id

    if backend == "local":
        path = entry.get("path")
        if not path:
            raise ValueError(f"workspace {ws_id!r}: local backend needs 'path'")
        storage = WorkspaceStorage.local(path)

    elif backend == "nextcloud":
        nc_root = entry.get("nextcloud_root", ws_id)
        base_url = entry.get("nextcloud_base_url") or _nc_default_base_url()
        username = entry.get("nextcloud_username") or os.environ.get("NEXTCLOUD_BASIC_USERNAME", "")
        password = entry.get("nextcloud_password") or os.environ.get("NEXTCLOUD_BASIC_PASSWORD", "")
        if not (base_url and username and password):
            raise ValueError(
                f"workspace {ws_id!r}: nextcloud backend needs NEXTCLOUD_BASE_URL + "
                "NEXTCLOUD_BASIC_USERNAME + NEXTCLOUD_BASIC_PASSWORD (env or per-entry override)"
            )
        storage = WorkspaceStorage.webdav(base_url, username, password, nc_root)

    elif backend == "fsspec":
        protocol = entry.get("protocol")
        root = entry.get("root")
        if not (protocol and root):
            raise ValueError(f"workspace {ws_id!r}: fsspec backend needs 'protocol' + 'root'")
        opts = entry.get("options", {}) or {}
        storage = WorkspaceStorage.from_fsspec(protocol, root, **opts)

    else:
        raise ValueError(f"workspace {ws_id!r}: unknown backend {backend!r}")

    return WorkspaceContext(
        id=ws_id,
        name=name,
        storage=storage,
        graphdb_repository=graphdb_repo,
        description=description,
        tags=tags,
    )


def _nc_default_base_url() -> Optional[str]:
    base = os.environ.get("NEXTCLOUD_BASE_URL")
    user = os.environ.get("NEXTCLOUD_BASIC_USERNAME")
    if not (base and user):
        return None
    # Many configs already include /remote.php/dav/files/<user>; if not, add it.
    if "/remote.php/dav/files/" in base:
        return base
    return f"{base.rstrip('/')}/remote.php/dav/files/{user}"


def _bundled_demo_contexts() -> list[WorkspaceContext]:
    """The bundled demo workspace(s), always available (tagged 'demo')."""
    out: list[WorkspaceContext] = []
    for ws_id in BUNDLED_DEMO_IDS:
        sub = BUNDLED_DEMO_DIR / ws_id
        if not sub.is_dir():
            continue
        name, description, tags = ws_id, "", ["demo"]
        meta = sub / "workspace_meta" / "metadata.json"
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                name = m.get("name", name)
                description = m.get("description", "")
                tags = list(dict.fromkeys((m.get("tags", []) or []) + ["demo"]))
            except Exception:
                pass
        out.append(
            WorkspaceContext(
                id=ws_id,
                name=name,
                storage=WorkspaceStorage.local(str(sub.resolve())),
                graphdb_repository=ws_id,
                description=description,
                tags=tags,
            )
        )
    return out


def _autodiscover_local_workspaces(usecases_dir: Path) -> list[WorkspaceContext]:
    contexts: list[WorkspaceContext] = []
    if not usecases_dir.exists():
        return contexts

    # Auto-discovered workspaces share the platform's default GraphDB repo
    # (set via LOCAL_WORKSPACE) until per-workspace GraphDB provisioning lands.
    # Each workspace's data lives in its own named graph within that repo.
    shared_repo = os.environ.get("LOCAL_WORKSPACE", "workspace_demo")

    for sub in sorted(usecases_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        # A folder qualifies as a workspace if it has at least one of the
        # populated canonical signals.
        signals = [
            sub / "ontology" / "extensions",
            sub / "scenarios",
            sub / "ingestion" / "output",
        ]
        if not any(s.exists() for s in signals):
            continue

        meta_path = sub / "workspace_meta" / "metadata.json"
        name = sub.name
        description = ""
        tags = []
        if meta_path.exists():
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
                name = m.get("name", name)
                description = m.get("description", "")
                tags = m.get("tags", []) or []
            except Exception:
                pass

        contexts.append(
            WorkspaceContext(
                id=sub.name,
                name=name,
                storage=WorkspaceStorage.local(str(sub.resolve())),
                graphdb_repository=sub.name,
                description=description,
                tags=tags,
            )
        )
    return contexts


# --------------------------------------------------------------------------
# NextCloud auto-discovery
# --------------------------------------------------------------------------
#
# When NextCloud is configured (via env or the GUI connector), workspaces stored
# on the server should import automatically — the server, not a local YAML, is
# the source of truth. A folder is treated as a workspace when it contains
# `workspace_meta/metadata.json` (the canonical signal that separates workspaces
# from NextCloud's default folders like Documents/Photos/global). The optional
# `workspace_` folder-name prefix is for human clarity only; discovery does not
# depend on it.
#
# Cached briefly because load_registry() runs on every render and each discovery
# does several WebDAV PROPFINDs.

_NC_DISCOVERY_CACHE: dict = {"key": None, "ts": 0.0, "contexts": []}
_NC_DISCOVERY_TTL = 60.0

# NextCloud's own default folders — never workspaces, skip without a PROPFIND.
_NC_DEFAULT_FOLDERS = {"global", "documents", "photos", "templates"}


def clear_nextcloud_discovery_cache() -> None:
    """Force the next load_registry() to re-scan NextCloud (e.g. after connect
    or after creating a NextCloud workspace)."""
    _NC_DISCOVERY_CACHE.update(key=None, ts=0.0, contexts=[])


def _autodiscover_nextcloud_workspaces() -> list[WorkspaceContext]:
    base = os.environ.get("NEXTCLOUD_BASE_URL")
    user = os.environ.get("NEXTCLOUD_BASIC_USERNAME")
    pw = os.environ.get("NEXTCLOUD_BASIC_PASSWORD")
    if not (base and user and pw):
        return []

    key = (base, user)
    now = time.time()
    if _NC_DISCOVERY_CACHE["key"] == key and (now - _NC_DISCOVERY_CACHE["ts"]) < _NC_DISCOVERY_TTL:
        return _NC_DISCOVERY_CACHE["contexts"]

    contexts: list[WorkspaceContext] = []
    try:
        import fsspec
        import webdav4.fsspec  # noqa: F401  — registers the 'webdav' protocol
        dav_base = f"{base.rstrip('/')}/remote.php/dav/files/{user}"
        fs = fsspec.filesystem("webdav", base_url=dav_base, auth=(user, pw))

        for entry in fs.ls("", detail=True):
            try:
                if entry.get("type") != "directory":
                    continue
                name = entry.get("name", "").replace("\\", "/").rstrip("/").split("/")[-1]
                if not name or name.lower() in _NC_DEFAULT_FOLDERS:
                    continue
                # The canonical signal: a workspace has workspace_meta/metadata.json.
                if not fs.exists(f"{name}/workspace_meta/metadata.json"):
                    continue

                # Use the full WebDAV base (…/remote.php/dav/files/<user>), not the
                # raw NEXTCLOUD_BASE_URL — otherwise every storage call hits a
                # non-WebDAV URL and fails with 405 Method Not Allowed.
                storage = WorkspaceStorage.webdav(dav_base, user, pw, name)
                ws_name, description, tags = name, "", []
                try:
                    m = json.loads(storage.read_text("workspace_meta/metadata.json"))
                    ws_name = m.get("name", name)
                    description = m.get("description", "")
                    tags = m.get("tags", []) or []
                except Exception:
                    pass

                contexts.append(
                    WorkspaceContext(
                        id=name,
                        name=ws_name,
                        storage=storage,
                        graphdb_repository=name,
                        description=description,
                        tags=tags,
                    )
                )
            except Exception:
                continue  # one bad folder shouldn't break discovery
    except Exception as exc:
        import sys
        print(f"[workspace-registry] NextCloud discovery skipped: {exc}", file=sys.stderr)
        return _NC_DISCOVERY_CACHE["contexts"]  # serve last-good on transient errors

    _NC_DISCOVERY_CACHE.update(key=key, ts=now, contexts=contexts)
    return contexts


def load_registry(strict: bool = False) -> WorkspaceRegistry:
    """Load workspaces from the configured registry file + auto-discovery.

    Behaviour:

    - If a workspaces.yaml exists, every entry in it is registered.
    - In addition, any folder under USECASES_DIR that looks like a workspace
      (and isn't already in the YAML) is registered as a local workspace.

    Set `strict=True` to skip auto-discovery and only honour the YAML.
    """
    contexts: list[WorkspaceContext] = []
    seen_ids: set[str] = set()

    # Always offer the bundled demo workspace(s) first.
    for ctx in _bundled_demo_contexts():
        if ctx.id not in seen_ids:
            contexts.append(ctx)
            seen_ids.add(ctx.id)

    yaml_path = _registry_path()
    if yaml_path is not None:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        for entry in data.get("workspaces", []) or []:
            try:
                ctx = _make_context_from_entry(entry)
            except Exception as exc:
                # Skip broken entries rather than blocking startup; log to stderr.
                import sys
                print(f"[workspace-registry] skipping {entry.get('id', '<unknown>')}: {exc}", file=sys.stderr)
                continue
            contexts.append(ctx)
            seen_ids.add(ctx.id)

    if not strict:
        for ctx in _autodiscover_local_workspaces(_usecases_dir()):
            if ctx.id not in seen_ids:
                contexts.append(ctx)
                seen_ids.add(ctx.id)

        # NextCloud-backed workspaces, discovered live from the server whenever
        # NextCloud is configured (env or the GUI connector). The server is the
        # source of truth, so these need no workspaces.yaml entry.
        for ctx in _autodiscover_nextcloud_workspaces():
            if ctx.id not in seen_ids:
                contexts.append(ctx)
                seen_ids.add(ctx.id)

    return WorkspaceRegistry(contexts=contexts)
