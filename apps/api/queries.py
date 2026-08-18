"""Query Manager endpoints — recommended queries (workspace + per instance).

Reuses the backend's ASK-preflighted recommendation builders so the React Query
Manager offers the same landing set and Instance Inspector as Streamlit, derived
from the core ontology's property/class hierarchy.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["queries"])


@router.get("/recommendations")
def recommendations(
    instance: Optional[str] = None,
    ctx: WorkspaceContext = Depends(get_ctx),
) -> list[dict[str, Any]]:
    """Recommended queries. With ``instance=<iri>`` these are the Instance
    Inspector's queries about that instance; without it, the workspace landing set."""
    client = graph_client(ctx)
    if instance:
        from backend.graphdb.queries.inspector import available_recommendations
        recs = available_recommendations(client, instance)
    else:
        from backend.graphdb.queries import available_workspace_queries
        recs = available_workspace_queries(client)
    return [
        {
            "key": r.get("key", ""),
            "name": r["name"],
            "description": r.get("description", ""),
            "sparql": r["sparql"],
        }
        for r in recs
    ]
