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
from .graphdb_provisioning import ensure_workspace_repo
from .registry import WorkspaceRegistry, load_registry
from .storage import WorkspaceStorage

__all__ = [
    "WorkspaceContext",
    "WorkspaceRegistry",
    "WorkspaceStorage",
    "create_workspace",
    "ensure_workspace_repo",
    "load_registry",
    "slugify",
    "workspace_id_exists",
]
