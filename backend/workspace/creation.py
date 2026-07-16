# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Create and initialise new workspaces.

Given a name and a chosen storage backend, this:

1. Creates the canonical workspace folder layout (see storage.CANONICAL_SUBDIRS).
2. Writes `workspace_meta/metadata.json`.
3. Registers NextCloud / fsspec workspaces in workspaces.yaml (local workspaces
   are auto-discovered under $USECASES_DIR, so they need no registry entry).
4. Provisions the triplestore dataset (creates it + loads the core ontology into
   the canonical named graphs) so the workspace is ready to use immediately.

Returns the new `WorkspaceContext`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .context import WorkspaceContext
from .graphdb_provisioning import ensure_workspace_repo
from .registry import (
    DEFAULT_REGISTRY,
    DEFAULT_USECASES_DIR,
    _nc_default_base_url,
    _registry_path,
    load_registry,
)
from .storage import WorkspaceStorage

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(name: str) -> str:
    """Turn a display name into a safe workspace id (folder/dataset name)."""
    s = (name or "").strip().lower().replace(" ", "_")
    s = _SLUG_RE.sub("", s)
    return s.strip("_-")


def _usecases_dir() -> Path:
    return Path(os.environ.get("USECASES_DIR") or DEFAULT_USECASES_DIR)


def workspace_id_exists(ws_id: str) -> bool:
    try:
        if load_registry().by_id(ws_id) is not None:
            return True
    except Exception:
        pass
    # Also guard against a stray folder that hasn't been discovered yet.
    return (_usecases_dir() / ws_id).exists()


def create_workspace(
    name: str,
    workspace_id: Optional[str] = None,
    backend: str = "local",
    description: str = "",
    tags: Optional[list] = None,
    workspace_type: str = "",
    location: str = "",
    provision_graph: bool = True,
    nextcloud_opts: Optional[dict] = None,
) -> WorkspaceContext:
    """Create + initialise a new workspace and return its WorkspaceContext.

    backend: "local" (filesystem under $USECASES_DIR) or "nextcloud" (WebDAV).
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Workspace name is required.")

    ws_id = slugify((workspace_id or "").strip() or name)
    if not ws_id:
        raise ValueError("Could not derive a valid workspace id from the name.")

    backend = (backend or "local").lower()
    # NextCloud workspace folders get a clear `workspace_` prefix so they stand
    # out among the user's other NextCloud folders (matches the original
    # platform). Discovery finds them by their workspace_meta regardless, but the
    # prefix makes "what is and isn't a workspace" obvious when browsing NextCloud.
    if backend == "nextcloud" and not ws_id.startswith("workspace_"):
        ws_id = f"workspace_{ws_id}"

    if workspace_id_exists(ws_id):
        raise ValueError(f"A workspace with id '{ws_id}' already exists.")

    if backend == "local":
        root = _usecases_dir() / ws_id
        if root.exists():
            raise ValueError(f"Folder already exists: {root}")
        storage = WorkspaceStorage.local(str(root))
    elif backend == "nextcloud":
        opts = nextcloud_opts or {}
        base_url = opts.get("base_url") or _nc_default_base_url()
        username = opts.get("username") or os.environ.get("NEXTCLOUD_BASIC_USERNAME", "")
        password = opts.get("password") or os.environ.get("NEXTCLOUD_BASIC_PASSWORD", "")
        if not (base_url and username and password):
            raise ValueError(
                "NextCloud is not configured (need NEXTCLOUD_BASE_URL + "
                "NEXTCLOUD_BASIC_USERNAME + NEXTCLOUD_BASIC_PASSWORD)."
            )
        storage = WorkspaceStorage.webdav(base_url, username, password, ws_id)
    else:
        raise ValueError(f"Unknown storage backend: {backend!r}")

    # 1. Canonical folder layout
    storage.ensure_canonical_layout()

    # 2. Workspace metadata (drives the landing-page card)
    meta = {
        "name": name,
        "description": description,
        "type": workspace_type or "Custom",
        "location": location or ("NextCloud" if backend == "nextcloud" else "Local"),
        "tags": tags or [],
        "status": "active",
        "version": "0.1.0",
        "created_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    storage.write_text("workspace_meta/metadata.json", json.dumps(meta, indent=2))

    # 3. fsspec/other backends aren't auto-discovered — register them in the
    #    YAML. NextCloud workspaces are discovered live from the server (by their
    #    workspace_meta), so they need no YAML entry.
    if backend not in ("local", "nextcloud"):
        _register_in_yaml(ws_id, name, backend, description, tags or [], nextcloud_root=ws_id)

    ctx = WorkspaceContext(
        id=ws_id,
        name=name,
        storage=storage,
        graphdb_repository=ws_id,
        description=description,
        tags=tags or [],
    )

    # 4. Provision the triplestore so the workspace is immediately usable
    #    (dataset created + core ontology loaded into the named graphs).
    if provision_graph:
        ensure_workspace_repo(ctx)

    # A new NextCloud workspace should appear in discovery immediately.
    if backend == "nextcloud":
        try:
            from .registry import clear_nextcloud_discovery_cache
            clear_nextcloud_discovery_cache()
        except Exception:
            pass

    return ctx


def _register_in_yaml(ws_id, name, backend, description, tags, nextcloud_root=None):
    path = _registry_path() or DEFAULT_REGISTRY
    data = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    entries = list(data.get("workspaces") or [])
    entry = {
        "id": ws_id,
        "name": name,
        "backend": backend,
        "description": description,
        "tags": tags,
    }
    if backend == "nextcloud":
        entry["nextcloud_root"] = nextcloud_root or ws_id
    entries.append(entry)
    data["workspaces"] = entries
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
