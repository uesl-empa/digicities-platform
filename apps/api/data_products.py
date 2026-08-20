# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Data Products endpoints — the same listings the Streamlit Data Products tab shows.

Reuses ``backend.data_products`` (the Phase 5 headless processor + analyzer):
private products come from the workspace's ``private_data_products/`` via its
storage, open/global ones from the local library dir
(``GLOBAL_DATA_PRODUCTS_DIR``) — no NextCloud needed in local mode, exactly
like the tab. The legacy NextCloud fallback still applies when the env
credentials are configured, because the processor carries it.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.data_products import DataProductProcessor, analyzer
from backend.workspace import WorkspaceContext
from backend.workspace.storage import WorkspaceStorage

from .deps import get_ctx, ws_root

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["data-products"])

# Row cap for parsed CSV resources (the response notes the cap via max_rows/truncated).
CSV_MAX_ROWS = 500


def _processor(ctx: WorkspaceContext) -> DataProductProcessor:
    """A headless processor for this workspace.

    Mirrors the Streamlit tab's resolution: the workspace's own storage when
    the context carries one, else the workspace tree under ``ws_root`` wrapped
    as local storage (pure local mode, no registry/NextCloud required).
    """
    storage = getattr(ctx, "storage", None)
    if storage is None:
        root = ws_root(ctx)
        if root.is_dir():
            storage = WorkspaceStorage.local(str(root))
    return DataProductProcessor(workspace_id=ctx.id, workspace_storage=storage)


def _scopes(scope: Optional[str]) -> list[tuple[str, bool]]:
    """(scope-name, is_private) pairs to try, honoring an explicit ?scope=."""
    if scope == "private":
        return [("private", True)]
    if scope == "open":
        return [("open", False)]
    return [("private", True), ("open", False)]


@router.get("/data-products")
def list_data_products(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Available data products (workspace-private + open/global) with fast
    metadata — no TTL parsing, same as the tab's listing pass."""
    proc = _processor(ctx)
    out: list[dict[str, Any]] = []
    for scope_name, is_private in (("private", True), ("open", False)):
        names = proc.list_private_folders() if is_private else proc.list_open_folders()
        for name in names:
            item: dict[str, Any] = {"name": name, "scope": scope_name}
            meta = proc.get_product_metadata(name, is_private=is_private)
            if meta:
                item["components"] = meta.get("component_count")   # fast estimate
                item["resources"] = meta.get("resource_count")
                item["ttl_path"] = meta.get("ttl_path")
            out.append(item)
    return out


@router.get("/data-products/{name}")
def data_product_detail(
    name: str,
    scope: Optional[str] = Query(None, pattern="^(private|open)$"),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """One product, fully processed: metadata + extracted component list +
    resource files. Without ``?scope=``, private is tried before open."""
    proc = _processor(ctx)
    for scope_name, is_private in _scopes(scope):
        product = proc.process_data_product(name, is_private=is_private)
        if product:
            return {
                "name": product["name"],
                "scope": scope_name,
                "folder_path": product.get("folder_path"),
                "ttl_path": product.get("ttl_path"),
                "component_count": product.get("component_count", 0),
                "component_types": sorted(product.get("components", {}).keys()),
                "components": product.get("components", {}),
                "resources": product.get("resources", []),
            }
    raise HTTPException(status_code=404, detail=f"data product '{name}' not found")


@router.get("/data-products/{name}/resource")
def data_product_resource(
    name: str,
    path: str = Query(..., description="resource path or filename within the product"),
    scope: Optional[str] = Query(None, pattern="^(private|open)$"),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Load one resource file, parsed for the known formats:

    * CSV     -> ``{"format": "csv", "columns": [...], "rows": [...] }`` with
      rows capped at ``CSV_MAX_ROWS`` (``truncated``/``max_rows`` note the cap)
    * GeoJSON -> ``{"format": "geojson", "content": {...}, "summary": {...}}``
    * EPW/other text -> ``{"format": ..., "text": <head>, "truncated": ...}``

    Only the filename component of ``path`` is used — the processor resolves it
    inside the product's ``resources/`` folder, so traversal can't escape it.
    """
    filename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not filename:
        raise HTTPException(status_code=400, detail="a resource filename is required")

    proc = _processor(ctx)
    for scope_name, is_private in _scopes(scope):
        product = proc.process_data_product(name, is_private=is_private)
        if not product:
            continue
        data = proc.load_resource_file(product, filename)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"resource '{filename}' not found in data product '{name}'")
        payload = analyzer.resource_payload(data, filename, max_rows=CSV_MAX_ROWS)
        payload.update({"name": filename, "product": name, "scope": scope_name})
        return payload
    raise HTTPException(status_code=404, detail=f"data product '{name}' not found")
