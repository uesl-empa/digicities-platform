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


ATTRIBUTE_TYPES = [
    "Physical", "Simple Cost", "Unit-Based Cost", "Curve", "Categorical",
    "Geospatial", "CustomPhysicalRatio", "Event", "SimpleValue",
]


@router.get("/meta")
def meta(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Form vocabulary: attribute types, QUDT unit codes, temporal precisions."""
    of = _funcs(ctx)
    return {
        "attribute_types": ATTRIBUTE_TYPES,
        "qudt_units": of.get_qudt_units(),
        "temporal_precisions": of.get_temporal_precisions(),
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


@router.post("/attribute/remove")
def remove_attribute(body: RemoveUri, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.remove_attribute(body.extension, body.uri))


@router.post("/link/remove")
def remove_link(body: LinkAttribute, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.remove_attribute_link(body.extension, body.component, body.attribute))


@router.get("/component/attributes")
def component_attributes(extension: str, component: str, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(extension)
    return of.get_component_attributes(extension, component)


@router.get("/categories")
def categories(extension: str, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(extension)
    return of.get_attribute_categories(extension)


@router.get("/categorical-attributes")
def categorical_attributes(extension: str, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(extension)
    return of.get_categorical_attributes(extension)


@router.get("/named-individuals")
def named_individuals(extension: str, attribute: str, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(extension)
    return of.get_named_individuals(extension, attribute)


class AddCategory(BaseModel):
    extension: str
    attribute: str
    category: str


class AddNamedIndividual(BaseModel):
    extension: str
    label: str
    attribute: str


class ExtRef(BaseModel):
    extension: str


@router.post("/attribute/category")
def add_to_category(body: AddCategory, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.add_attribute_to_category(body.extension, body.attribute, body.category))


@router.post("/named-individual")
def add_named_individual(body: AddNamedIndividual, ctx: WorkspaceContext = Depends(get_ctx)):
    of = _funcs(ctx)
    of.load_extension_and_update(body.extension)
    return _apply(*of.add_named_individual(body.extension, body.label, body.attribute))


@router.get("/export")
def export(extension: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, str]:
    """The extension's TTL, for the Publish/Download."""
    ttl = _funcs(ctx).get_export_ttl_content(extension) or ""
    return {"extension": extension, "ttl": ttl}


@router.post("/publish")
def publish(body: ExtRef, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Update the temp working graph and export it (the Publish action)."""
    return _funcs(ctx).update_temp_and_export(body.extension)


# ── mapping subsystem: map ontology terms onto a source model's classes/properties ──
class MapClass(BaseModel):
    chosen: str
    linkage_relation: str
    mapping_class: str
    mapping: str


class MapProp(BaseModel):
    chosen: str
    linkage_relation: str
    mapping_property: str
    mapping: str


class RemovePropMapping(BaseModel):
    mapping: str
    subject: str
    predicate: str
    object: str


@router.get("/mapping/inputs")
def mapping_inputs(ctx: WorkspaceContext = Depends(get_ctx)) -> list[str]:
    return _funcs(ctx).list_mapping_inputs()


@router.get("/mapping/classes")
def mapping_classes(mapping: str, ctx: WorkspaceContext = Depends(get_ctx)):
    return _funcs(ctx).get_mapping_classes(mapping)


@router.get("/mapping/properties")
def mapping_properties(mapping: str, ctx: WorkspaceContext = Depends(get_ctx)):
    return _funcs(ctx).get_mapping_properties(mapping)


@router.get("/mapping/property-mappings")
def property_mappings(mapping: str, ctx: WorkspaceContext = Depends(get_ctx)):
    return _funcs(ctx).get_property_mappings(mapping)


@router.post("/mapping/component")
def map_component(body: MapClass, ctx: WorkspaceContext = Depends(get_ctx)):
    return _apply(*_funcs(ctx).map_component(body.chosen, body.linkage_relation, body.mapping_class, body.mapping))


@router.post("/mapping/attribute")
def map_attribute(body: MapClass, ctx: WorkspaceContext = Depends(get_ctx)):
    return _apply(*_funcs(ctx).map_attribute(body.chosen, body.linkage_relation, body.mapping_class, body.mapping))


@router.post("/mapping/property")
def map_property(body: MapProp, ctx: WorkspaceContext = Depends(get_ctx)):
    return _apply(*_funcs(ctx).map_property(body.chosen, body.linkage_relation, body.mapping_property, body.mapping))


@router.post("/mapping/property-mapping/remove")
def remove_property_mapping(body: RemovePropMapping, ctx: WorkspaceContext = Depends(get_ctx)):
    return _apply(*_funcs(ctx).remove_property_mapping(body.mapping, body.subject, body.predicate, body.object))
