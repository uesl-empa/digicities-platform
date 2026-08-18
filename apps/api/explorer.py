"""Digital Replica Explorer endpoints — the same data the Streamlit explorer shows.

Reuses the *data* half of ``apps/streamlit/components/component_explorer.py``
(all Streamlit-free: types, per-type instance table, unit formatting, curve
parsing, provenance) so the React explorer renders exactly what Streamlit did,
without reimplementing 1400 lines of attribute processing in TypeScript.
"""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["explorer"])


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


@router.get("/components")
def component_types(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Component classes with instance counts (the explorer's left-hand list)."""
    from apps.streamlit.components.component_explorer import get_component_types_with_instances

    df = get_component_types_with_instances(graph_client(ctx))
    if df is None or df.empty:
        return []
    return [
        {"type": str(r.componentType), "name": str(r.componentName), "count": int(r.instanceCount)}
        for r in df.itertuples()
    ]


@router.get("/components/{name}")
def component_table(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """The instance × attribute table for one component type — values already
    carry units (``85.0 m``, ``Curve (25 points): KiloW vs M/SEC``). Curve points
    are returned separately, keyed by instance id, so the UI can chart them."""
    from apps.streamlit.components.component_explorer import (
        get_component_data_unified,
        process_enhanced_component_data,
        get_component_sources,
        attach_sources,
        get_visible_columns,
        curve_columns,
    )

    client = graph_client(ctx)
    instances, attributes = get_component_data_unified(client, name)
    if not instances:
        return {"columns": [], "rows": [], "curves": {}, "sources": {}, "has_sources": False}

    df = process_enhanced_component_data(instances, attributes)
    df = attach_sources(df, get_component_sources(client, name))
    columns = get_visible_columns(df)
    ccols = curve_columns(df)

    # Per-instance provenance for the "Data sources" panel (keyed by instance id).
    sources: dict[str, Any] = {}
    if "_sources" in df.columns:
        for _, row in df.iterrows():
            meta = row.get("_sources")
            if isinstance(meta, dict):
                sources[str(row.get("instance_id"))] = meta
    has_sources = "Source" in columns

    curves: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        iid = str(row.get("instance_id"))
        per: dict[str, Any] = {}
        for cc in ccols:
            meta = row.get(f"_curve__{cc}")
            if isinstance(meta, dict) and meta.get("points"):
                per[cc] = {
                    "points": [[float(x), float(y)] for x, y in meta["points"]],
                    "x_unit": meta.get("x_unit"),
                    "y_unit": meta.get("y_unit"),
                }
        if per:
            curves[iid] = per

    rows = [{c: _clean(row.get(c)) for c in columns} for _, row in df.iterrows()]
    return {
        "columns": columns,
        "rows": rows,
        "curves": curves,
        "sources": sources,
        "has_sources": has_sources,
    }
