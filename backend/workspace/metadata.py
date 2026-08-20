# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workspace metadata — the one reader for ``workspace_meta/metadata.json``.

Both frontends (Streamlit's landing page / sidebar and the REST API's
``workspace_info``) previously read the metadata file with their own copies of
the same logic. This module is the single implementation.

Priority:

1. Registry-aware: read from the workspace's own storage (works for local FS,
   NextCloud-backed, or any other fsspec backend the registry knows about).
2. Legacy fallback: ``global/workspace_meta/<id>/metadata.json`` on NextCloud.
"""
from __future__ import annotations

import json
from typing import Optional

METADATA_PATH = "workspace_meta/metadata.json"


def _registry_context(workspace_id: str):
    """Look up the workspace in the registry, return its WorkspaceContext or None."""
    try:
        from .registry import load_registry
        return load_registry().by_id(workspace_id)
    except Exception:
        return None


def read_workspace_metadata(ctx) -> dict:
    """Read ``workspace_meta/metadata.json`` from a WorkspaceContext's storage.

    Returns {} when the file is missing, unreadable, or not a JSON object.
    """
    if ctx is None:
        return {}
    try:
        if not ctx.storage.exists(METADATA_PATH):
            return {}
        metadata = json.loads(ctx.storage.read_text(METADATA_PATH))
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}


def _legacy_nextcloud_metadata(workspace_id: str) -> dict:
    """Legacy layout: global/workspace_meta/<id>/metadata.json on NextCloud."""
    try:
        from backend.nextcloud import create_client_from_env
        client = create_client_from_env("global")
        if client is None:
            return {}
        content = client.download_text_file(f"workspace_meta/{workspace_id}/metadata.json")
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        metadata = json.loads(content.strip())
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}


def load_workspace_metadata(workspace_id: str, ctx=None) -> dict:
    """Load a workspace's metadata dict by id (registry-aware, with legacy fallback).

    ``ctx`` short-circuits the registry lookup when the caller already holds
    the workspace's WorkspaceContext.
    """
    if ctx is None or getattr(ctx, "id", None) != workspace_id:
        ctx = _registry_context(workspace_id)

    metadata = read_workspace_metadata(ctx)
    if not metadata:
        metadata = _legacy_nextcloud_metadata(workspace_id)
    return metadata
