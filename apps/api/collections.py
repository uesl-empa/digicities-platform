# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Collections endpoints — dataset-level statistics over attribute values.

Wraps ``backend.collections`` (the same functions the Streamlit Collections
module and the Replica Explorer dropdown call): list what is materialized,
read one collection's statistics and distribution, build/recompute a Set or
GroupedSet (grouping by a second attribute's values OR by a linked component
class — the backend dispatches semantically), and delete one.

Collections are DERIVED artefacts in the ``<http://collections>`` named graph:
a workspace data reload invalidates them (fingerprint-based — a plain
re-provision preserves them), and every materialization is an idempotent
surgical replace, so POST is safe to repeat.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext
from backend.collections import (
    CollectionError,
    delete_collection,
    list_collections,
    materialize_grouped_set,
    materialize_set,
    member_count,
    set_bins,
    set_statistics,
    workspace_attribute_types,
    workspace_component_types,
    workspace_datasets,
)

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["collections"])

_DICI = "https://digicities.info/ontology#"


def _iri(term: str) -> str:
    """Accept a full IRI or a dici_onto local name."""
    return term if term.startswith(("http://", "https://")) else _DICI + term


def _local(iri: Any) -> str:
    return str(iri).rstrip("#/").split("#")[-1].split("/")[-1]


def _clean(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if pd.isna(v):
        return None
    return str(v)


def _rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return [{k: _clean(v) for k, v in row.items()} for _, row in df.iterrows()]


def _collection_by_name(client, name: str) -> pd.Series:
    df = list_collections(client)
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            if _local(row["collection"]) == name:
                return row
    raise HTTPException(status_code=404, detail=f"collection '{name}' not found")


class MaterializeRequest(BaseModel):
    """What to aggregate. ``attribute``/``group_by``/``dataset`` accept full
    IRIs or dici_onto local names. ``group_by`` may be an attribute type
    (group by its values) or a component class (one group per linked
    instance). ``statistics`` selects which statistics component-grouping
    projects onto the container (numeric targets only)."""
    attribute: str
    group_by: Optional[str] = None
    dataset: Optional[str] = None
    statistics: list[str] = ["mean"]


@router.get("/collections")
def collections_index(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Top-level collections materialized for this workspace."""
    client = graph_client(ctx)
    out = []
    for row in _rows(list_collections(client)):
        row["name"] = _local(row["collection"])
        row["kind"] = _local(row["kind"]) if row.get("kind") else None
        out.append(row)
    return out


@router.get("/collections/options")
def collections_options(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """What a collection can be built from: the workspace's attribute types,
    the linked component classes (component grouping), and the data sources
    (optional restriction)."""
    client = graph_client(ctx)
    return {
        "attribute_types": _rows(workspace_attribute_types(client)),
        "component_types": _rows(workspace_component_types(client)),
        "datasets": _rows(workspace_datasets(client)),
    }


@router.get("/collections/{name}")
def collection_detail(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """One collection's statistics, distribution bins and membership. For a
    GroupedSet the statistics/bins rows carry each group's ``groupKey``."""
    client = graph_client(ctx)
    row = _collection_by_name(client, name)
    coll = str(row["collection"])
    detail = {
        "name": name,
        "collection": coll,
        "kind": _local(row["kind"]),
        "attribute_type": _clean(row.get("attrType")),
        "grouped_by": _clean(row.get("groupedBy")),
        "dataset": _clean(row.get("dataset")),
        "computed_at": _clean(row.get("computedAt")),
        "statistics": _rows(set_statistics(client, coll)),
        "bins": _rows(set_bins(client, coll)),
    }
    if detail["kind"] == "Set":
        detail["member_count"] = member_count(client, coll)
    return detail


@router.post("/collections", status_code=201)
def materialize(body: MaterializeRequest,
                ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Materialize (or idempotently recompute) a Set / GroupedSet."""
    client = graph_client(ctx)
    dataset = _iri(body.dataset) if body.dataset else None
    try:
        if body.group_by:
            iri = materialize_grouped_set(
                client, ctx.id, _iri(body.attribute), _iri(body.group_by),
                dataset, project_statistics=tuple(body.statistics))
        else:
            iri = materialize_set(client, ctx.id, _iri(body.attribute), dataset)
    except CollectionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"collection": iri, "name": _local(iri)}


@router.delete("/collections/{name}")
def remove(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Delete one materialized collection (its sets, statistics, bins,
    membership links and projected aggregates)."""
    client = graph_client(ctx)
    row = _collection_by_name(client, name)
    delete_collection(client, str(row["collection"]))
    return {"deleted": name}
