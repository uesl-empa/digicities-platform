# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workspace abstraction layer.

A workspace is a folder with the canonical Digicities layout (see
docs/WORKSPACE_LAYOUT.md). This package provides:

- `WorkspaceStorage` — fsspec-backed I/O over a workspace's canonical subdirs.
- `WorkspaceContext` — per-session container (id, name, storage, paths).
- `WorkspaceRegistry` — loads workspaces.yaml and produces WorkspaceContext objects.

Modules that previously used hardcoded `data/...` paths or a `NextcloudClient`
should accept a `WorkspaceContext` instead. The same code paths then work for
both local-filesystem and NextCloud workspaces.
"""

from .context import WorkspaceContext
from .creation import create_workspace, slugify, workspace_id_exists
from .deletion import (WorkspaceProtected, clear_workspace, delete_workspace,
                       touch_workspace_activity, workspace_last_updated)
from .graphdb_provisioning import ensure_workspace_repo
from .lifecycle import (OpenedWorkspace, build_graph_client, check_connection,
                        open_workspace)
from .metadata import load_workspace_metadata, read_workspace_metadata
from .paths import resolve_workspace_local_path, to_host_display_path
from .registry import WorkspaceRegistry, load_registry
from .storage import WorkspaceStorage

__all__ = [
    "OpenedWorkspace",
    "WorkspaceContext",
    "WorkspaceProtected",
    "WorkspaceRegistry",
    "WorkspaceStorage",
    "build_graph_client",
    "check_connection",
    "clear_workspace",
    "create_workspace",
    "delete_workspace",
    "ensure_workspace_repo",
    "load_registry",
    "load_workspace_metadata",
    "open_workspace",
    "read_workspace_metadata",
    "resolve_workspace_local_path",
    "slugify",
    "to_host_display_path",
    "touch_workspace_activity",
    "workspace_id_exists",
    "workspace_last_updated",
]
