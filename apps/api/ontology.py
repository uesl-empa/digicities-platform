"""Ontology Manager endpoints — reuse backend.ontology_manager.OntologyFunctions.

The Streamlit Ontology Manager is a stateful editor: you *load* an extension
(which merges it with the core ontology into a temp working graph), then explore
its components / attributes / properties and edit them. These endpoints wrap the
same pure functions so the React Ontology Manager shows and edits the same data.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}/ontology", tags=["ontology"])


def _funcs(ctx: WorkspaceContext):
    from backend.ontology_manager import OntologyFunctions
    return OntologyFunctions(
        storage=getattr(ctx, "storage", None),
        workspace_id=ctx.id,
        graphdb_client=graph_client(ctx),
    )


@router.get("/extensions")
def extensions(ctx: WorkspaceContext = Depends(get_ctx)) -> list[str]:
    """The workspace's ontology extension files (the 'Load Existing Extension' list)."""
    return _funcs(ctx).list_extension_files()


@router.get("/data")
def ontology_data(extension: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Load an extension (extension + core, merged) and return its components,
    attributes and properties — the loaded interface's Classes/Properties/Operations."""
    of = _funcs(ctx)
    ok, message = of.load_extension_and_update(extension)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {
        "extension": extension,
        "components": of.explore_components(extension),
        "attributes": of.explore_attributes(extension),
        "properties": of.explore_properties(extension),
    }


@router.get("/range")
def component_range(
    extension: str,
    component: str,
    ctx: WorkspaceContext = Depends(get_ctx),
) -> list[dict[str, Any]]:
    """The Component Range Explorer: the ranges reachable from a component's properties."""
    of = _funcs(ctx)
    of.load_extension_and_update(extension)
    return of.get_component_range(extension, component)
