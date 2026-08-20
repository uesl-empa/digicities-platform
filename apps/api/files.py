# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workspace file browsing — the storage-parity gap the Streamlit app covers
implicitly (every tab reads the workspace tree) and the REST surface didn't.

Read-only: directory listings and small-file fetches inside a workspace's
file root (``deps.ws_root``). Every path is resolved and checked against the
root, so ``..`` or absolute paths can't escape it.
"""
from __future__ import annotations

import mimetypes
import pathlib
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.workspace import WorkspaceContext

from .deps import get_ctx, ws_root

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["files"])

# Small-file cap for /content — big artifacts (parquet, archives) don't belong
# in a JSON-era browsing endpoint; fetch those through purpose-built routes.
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2 MB

# Deterministic types for the platform's own file formats. Python's mimetypes
# consults the OS (the Windows registry maps .csv to Excel, for one), so the
# workspace-native extensions are pinned here.
_KNOWN_TYPES = {
    ".csv": "text/csv",
    ".ttl": "text/turtle",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".epw": "text/plain",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _guess_type(name: str) -> str:
    suffix = pathlib.PurePosixPath(name).suffix.lower()
    if suffix in _KNOWN_TYPES:
        return _KNOWN_TYPES[suffix]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _resolve(ctx: WorkspaceContext, rel: str) -> tuple[pathlib.Path, pathlib.Path]:
    """(workspace root, requested path) — 400 when the path escapes the root."""
    root = ws_root(ctx).resolve()
    rel = (rel or "").strip()
    candidate = pathlib.Path(rel)
    if candidate.is_absolute() or candidate.drive:
        raise HTTPException(status_code=400, detail="path escapes the workspace root")
    target = (root / rel).resolve() if rel else root
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes the workspace root")
    return root, target


@router.get("/files")
def list_directory(
    path: Optional[str] = Query("", description="workspace-relative directory"),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """List one directory inside the workspace root (name, type, size, mtime)."""
    root, target = _resolve(ctx, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{path}' not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"'{path}' is not a directory")

    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        stat = child.stat()
        entries.append({
            "name": child.name,
            "type": "directory" if child.is_dir() else "file",
            "size": stat.st_size if child.is_file() else None,
            "mtime": stat.st_mtime,
        })
    rel = "" if target == root else target.relative_to(root).as_posix()
    return {"path": rel, "entries": entries}


@router.get("/files/content")
def file_content(
    path: str = Query(..., description="workspace-relative file path"),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> Response:
    """Fetch one small file (≤ 2 MB), with a guessed content type."""
    _, target = _resolve(ctx, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{path}' not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"'{path}' is a directory")

    size = target.stat().st_size
    if size > MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"'{path}' is {size} bytes; /content serves at most {MAX_CONTENT_BYTES}")

    return Response(content=target.read_bytes(), media_type=_guess_type(target.name))
