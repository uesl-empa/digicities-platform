"""Ontology Manager endpoints — reuse backend.ontology_manager.OntologyFunctions.

The Streamlit Ontology Manager is a stateful editor: you *load* an extension
(which merges it with the core ontology into a temp working graph), then explore
its components / attributes / properties and edit them. These endpoints wrap the
same pure functions so the React Ontology Manager shows and edits the same data.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}/ontology", tags=["ontology"])


class AddComponent(BaseModel):
    extension: str
    label: str
    parent: str


class AddAttribute(BaseModel):
    extension: str
    attribute_type: str
    label: str
    unit: str = ""
    unit_y: str = ""
    x_unit: str = ""


class LinkAttribute(BaseModel):
    extension: str
    component: str
    attribute: str


class RemoveUri(BaseModel):
    extension: str
    uri: str


class Reparent(BaseModel):
    extension: str
    uri: str
    new_parent: str


class CreateExtension(BaseModel):
    name: str


def _apply(ok: bool, message: str) -> dict[str, str]:
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


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


@router.get("/meta")
def meta(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Form vocabulary: the attribute types and QUDT unit codes for the add-attribute form."""
    of = _funcs(ctx)
    types = of.BASE_ATTRIBUTE_TYPES
    return {
        "attribute_types": list(types.keys()) if isinstance(types, dict) else list(types),
        "qudt_units": of.get_qudt_units(),
    }


# ── edits — every op persists to the extension file (verified), so a re-read shows it ──
@router.post("/component/add")
def add_component(body: AddComponent, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.add_component(body.extension, body.label, body.parent))


@router.post("/component/remove")
def remove_component(body: RemoveUri, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.remove_component(body.extension, body.uri))


@router.post("/component/reparent")
def reparent(body: Reparent, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.change_component_parent(body.extension, body.uri, body.new_parent))


@router.post("/attribute/add")
def add_attribute(body: AddAttribute, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.add_attribute(
        body.extension, body.attribute_type, body.label,
        qudt_unit=body.unit, y_qudt_unit=body.unit_y, x_unit=body.x_unit))


@router.post("/link")
def link_attribute(body: LinkAttribute, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.link_attribute(body.extension, body.component, body.attribute))


@router.post("/extension/create")
def create_extension(body: CreateExtension, ctx: WorkspaceContext = Depends(get_ctx)):
    return _apply(*_funcs(ctx).create_new_extension(body.name))
