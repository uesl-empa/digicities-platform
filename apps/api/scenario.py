"""Scenario Builder endpoints.

Pick component instances from the workspace into a scenario, then build the
scenario TTL and save it under scenarios/. Two builds share one endpoint
(issue #17): a reference-only spec uses the thin ``build_scenario_ttl``
(usedInScenario + ComponentLink edges); as soon as any component carries
``attributes``/``nested_properties`` the request becomes a full ScenarioDraft
and goes through ``backend.scenario_builder.emitter.generate_full_ttl`` — the
same emitter the Streamlit Scenario Builder uses.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client, ws_root

router = APIRouter(prefix="/api/workspaces/{workspace_id}/scenario", tags=["scenario"])



def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", name.strip()) or "scenario"


@router.get("/instances")
def instances(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Component types with their instance URIs, to pick into a scenario."""
    from backend.explorer import (
        get_component_types_with_instances,
        get_component_data_unified,
        process_enhanced_component_data,
    )

    client = graph_client(ctx)
    types = get_component_types_with_instances(client)
    if types is None or types.empty:
        return []
    out = []
    for r in types.itertuples():
        name = str(r.componentName)
        insts, attrs = get_component_data_unified(client, name)
        rows = []
        if insts:
            df = process_enhanced_component_data(insts, attrs)
            for _, row in df.iterrows():
                uri = row.get("URI")
                if isinstance(uri, str) and uri:
                    rows.append({"uri": uri, "label": str(row.get("instance_id") or row.get("label") or uri)})
        out.append({"component": name, "class": str(r.componentType), "instances": rows})
    return out


@router.get("/list")
def list_scenarios(ctx: WorkspaceContext = Depends(get_ctx)) -> list[str]:
    d = ws_root(ctx) / "scenarios"
    return sorted(p.name for p in d.glob("*.ttl")) if d.exists() else []


@router.get("/ttl")
def scenario_ttl(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, str]:
    p = ws_root(ctx) / "scenarios" / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    return {"name": name, "ttl": p.read_text(encoding="utf-8")}


def _resolve_service_template(ctx: WorkspaceContext, service: str) -> tuple[str, dict]:
    """A service template by file name or service_name from services/."""
    import yaml

    d = ws_root(ctx) / "services"
    candidates = (sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))) if d.exists() else []
    for p in candidates:
        if p.name == service or p.stem == service:
            return p.name, yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for p in candidates:
        try:
            t = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if t.get("service_name") == service:
            return p.name, t
    raise HTTPException(status_code=404, detail="service template not found")


@router.get("/requirements")
def service_requirements(service: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """The constraints a service template puts on a scenario: required
    component types, ``CL.Source.Target`` links, and required attributes
    (dotted ``Base.nestedProp`` form — the same form the emitter's
    completeness gate resolves). ``service`` is a file name or service_name
    under the workspace ``services/`` folder."""
    from backend.scenario_builder.requirements import parse_service_requirements

    file, template = _resolve_service_template(ctx, service)
    out = parse_service_requirements(template)
    out["file"] = file
    if not out.get("service_name"):
        out["service_name"] = file.rsplit(".", 1)[0]
    return out


@router.get("/draft")
def scenario_draft(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """A saved scenario parsed back into the builder's editable draft shape
    (components as uri/type/label, links with the 'scenario' pseudo-source),
    so an existing scenario can be reloaded, edited, and rebuilt."""
    from backend.scenario_builder.reload import draft_from_ttl

    p = ws_root(ctx) / "scenarios" / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        out = draft_from_ttl(p.read_text(encoding="utf-8"))
    except Exception as bad_ttl:
        raise HTTPException(status_code=400, detail=f"could not parse the scenario TTL: {bad_ttl}")
    out["file"] = name
    return out


class PushReq(BaseModel):
    name: str


@router.post("/push")
def push(req: PushReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Append a saved scenario to the <scenarios> named graph, so other
    modules (Convert tab, explorers) see it without reprovisioning — the
    Streamlit builder's 'upload to graph' button."""
    from backend.scenario_builder.publish import push_scenario_to_graph

    p = ws_root(ctx) / "scenarios" / req.name
    if not p.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        ok, status, _resp = push_scenario_to_graph(graph_client(ctx), p.read_text(encoding="utf-8"))
    except Exception as push_error:
        raise HTTPException(status_code=502, detail=f"Push failed: {push_error}")
    return {"ok": ok, "status_code": status, "name": req.name}


@router.delete("")
def delete_scenario(name: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Delete a saved scenario: the scenarios/ file, plus a best-effort
    removal of its triples from the <scenarios> graph (scoped to this
    scenario's usedInScenario marks; other scenarios are untouched)."""
    from backend.scenario_builder.publish import remove_scenario_from_graph
    from backend.scenario_builder.reload import draft_from_ttl

    p = ws_root(ctx) / "scenarios" / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    graph_cleaned = False
    try:
        scenario_uri = draft_from_ttl(p.read_text(encoding="utf-8")).get("scenario_uri")
        if scenario_uri:
            remove_scenario_from_graph(graph_client(ctx), scenario_uri)
            graph_cleaned = True
    except Exception:
        pass  # the file is the source of truth; graph cleanup is best-effort
    p.unlink()
    return {"deleted": name, "graph_cleaned": graph_cleaned}


@router.get("/link-suggestions")
def link_suggestions(service: str | None = None,
                     ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Physical component links discovered in the workspace graph
    (locatedIn / linksComponent subproperties), optionally matched to a
    service's CL.Source.Target requirements — each match oriented so
    suggested_source/suggested_target fulfil the requirement directly."""
    from backend.scenario_builder.link_discovery import (
        discover_component_links,
        match_links_to_requirements,
    )

    try:
        discovered = discover_component_links(graph_client(ctx))
    except Exception:
        discovered = []

    matched: dict[str, Any] = {}
    if service and discovered:
        from backend.scenario_builder.requirements import extract_component_links

        _, template = _resolve_service_template(ctx, service)
        matched = match_links_to_requirements(discovered, extract_component_links(template))

    return {"discovered": discovered, "matched": matched}


class ScenComponent(BaseModel):
    uri: str
    type: str | None = None
    label: str | None = None
    # Full-draft fields (issue #17) — shapes match the Scenario Builder's
    # session state, which is what backend.scenario_builder.emitter consumes.
    source: str | None = None
    attributes: dict[str, dict[str, Any]] | None = None
    nested_properties: dict[str, dict[str, Any]] | None = None


class ScenLink(BaseModel):
    source: str
    target: str
    link_type: str | None = None


class ScenarioSpec(BaseModel):
    scenario_name: str
    components: list[ScenComponent] = []
    links: list[ScenLink] = []
    service_name: str | None = None
    description: str | None = None
    ttl_specificity: str = "High"
    required_attributes: dict[str, list[str]] | None = None
    save: bool = True


class ValidateSpec(BaseModel):
    components: list[ScenComponent] = []
    links: list[ScenLink] = []
    # Either name a service (its template supplies the requirements) or pass
    # required_attributes directly; a direct pass wins.
    service: str | None = None
    required_attributes: dict[str, list[str]] | None = None


def _attach_graph_attributes(ctx: WorkspaceContext, comps: list[dict[str, Any]]) -> None:
    """Fill in attributes/nested_properties from the workspace graph for
    components that didn't bring their own — the builder UI only holds
    uri/type/label. Grouped per type so each type is one graph round-trip."""
    from backend.explorer import (
        get_component_data_unified,
        get_component_types_with_instances,
        structured_instance_attributes,
    )

    todo: dict[str, list[dict[str, Any]]] = {}
    for c in comps:
        if not c.get("attributes") and not c.get("nested_properties") and c.get("type"):
            todo.setdefault(c["type"], []).append(c)
    if not todo:
        return
    try:
        client = graph_client(ctx)
        # The explorer queries key on the display label ("Wind Turbine"); the
        # builder holds class local names ("WindTurbine") — map between them.
        types_df = get_component_types_with_instances(client)
        label_by_local = {}
        if types_df is not None and not types_df.empty:
            for r in types_df.itertuples():
                local = str(r.componentType).rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                label_by_local[local] = str(r.componentName)
    except Exception:
        return
    for type_name, members in todo.items():
        try:
            _, attrs = get_component_data_unified(client, label_by_local.get(type_name, type_name))
        except Exception:
            continue
        structured = structured_instance_attributes(attrs)
        for c in members:
            found = structured.get(c["uri"])
            if found:
                c["attributes"] = found["attributes"]
                c["nested_properties"] = found["nested_properties"]


@router.post("/validate")
def validate(spec: ValidateSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Check the picked components against a service's required attributes,
    and preview the emitter's completeness gate: components missing any
    required attribute are excluded from the built TTL, along with their
    links. Same resolver as the emitter, so this is exactly what a build
    would do."""
    from backend.scenario_builder.emitter import (
        get_filtered_components_for_ttl,
        get_filtered_links_for_ttl,
        resolve_nested_attribute_requirement,
    )

    required = spec.required_attributes
    if required is None and spec.service:
        from backend.scenario_builder.requirements import extract_required_attributes_enhanced

        _, template = _resolve_service_template(ctx, spec.service)
        required, _nested = extract_required_attributes_enhanced(template)
    required = required or {}

    comps = [{"uri": c.uri, "type": c.type, "label": c.label or c.uri,
              "attributes": c.attributes or {}, "nested_properties": c.nested_properties or {}}
             for c in spec.components]
    _attach_graph_attributes(ctx, [c for c in comps if required.get(c["type"] or "")])
    # The Streamlit builder injects URI/label as synthetic attributes on add
    # (templates reference them via e.g. Building.URI); mirror that here so
    # they never show up as missing.
    for comp in comps:
        comp["attributes"].setdefault("URI", {"value": comp["uri"]})
        comp["attributes"].setdefault("label", {"value": comp["label"]})

    results = []
    for comp in comps:
        reqs = required.get(comp["type"] or "", [])
        missing = []
        for req_attr in reqs:
            try:
                present = resolve_nested_attribute_requirement(comp, req_attr)
            except Exception:
                present = None
            if not present:
                missing.append(req_attr)
        if not reqs:
            status = "compliant"
        elif not missing:
            status = "compliant"
        elif len(missing) == len(reqs):
            status = "missing_all"
        else:
            status = "partial"
        results.append({"uri": comp["uri"], "type": comp["type"], "label": comp["label"],
                        "status": status, "missing": missing, "required": list(reqs)})

    included = get_filtered_components_for_ttl(comps, required)
    included_uris = {c["uri"] for c in included}
    for r in results:
        r["included"] = r["uri"] in included_uris

    links = [{"source": l.source, "target": l.target,
              **({"link_type": l.link_type} if l.link_type else {})} for l in spec.links]
    kept_links = get_filtered_links_for_ttl(links, included)

    return {
        "components": results,
        "summary": {
            "total": len(results),
            "compliant": sum(1 for r in results if r["status"] == "compliant"),
            "partial": sum(1 for r in results if r["status"] == "partial"),
            "missing_all": sum(1 for r in results if r["status"] == "missing_all"),
            "excluded": sum(1 for r in results if not r["included"]),
        },
        "links": {"total": len(links), "kept": len(kept_links),
                  "dropped": len(links) - len(kept_links)},
    }


def _wants_full_emitter(spec: ScenarioSpec) -> bool:
    """The full emitter kicks in as soon as any component carries attribute
    data; the thin reference-only build stays byte-for-byte what it was."""
    return any(c.attributes or c.nested_properties for c in spec.components)


@router.post("/build")
def build(spec: ScenarioSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    if not spec.scenario_name.strip():
        raise HTTPException(status_code=400, detail="Give the scenario a name.")
    if not spec.components:
        raise HTTPException(status_code=400, detail="Add at least one component to the scenario.")

    if _wants_full_emitter(spec):
        from backend.scenario_builder.draft import ScenarioDraft
        from backend.scenario_builder.emitter import generate_full_ttl

        comps: list[dict[str, Any]] = []
        for c in spec.components:
            comp: dict[str, Any] = {"uri": c.uri, "type": c.type, "label": c.label,
                                    "source": c.source, "attributes": c.attributes,
                                    "nested_properties": c.nested_properties}
            comps.append(comp)
        links = []
        for l in spec.links:
            link: dict[str, Any] = {"source": l.source, "target": l.target}
            if l.link_type is not None:
                link["link_type"] = l.link_type
            links.append(link)
        try:
            draft = ScenarioDraft.from_request(
                spec.scenario_name, ctx.id, comps, links,
                workspace_name=getattr(ctx, "name", None) or ctx.id,
                service_name=spec.service_name, description=spec.description,
                ttl_specificity=spec.ttl_specificity,
                required_attributes=spec.required_attributes,
            )
        except ValueError as bad_draft:
            raise HTTPException(status_code=400, detail=str(bad_draft))
        ttl = generate_full_ttl(draft)
    else:
        from backend.scenario_builder import build_scenario_ttl, scenario_uri_for

        comps = [{"uri": c.uri, "type": c.type, "label": c.label} for c in spec.components]
        # The builder UIs use the pseudo-source 'scenario' for automatic
        # scenario→component links; the full emitter substitutes the scenario
        # IRI itself, the thin builder emits sources verbatim — so do it here.
        sc = scenario_uri_for(ctx.id, spec.scenario_name)
        links = []
        for l in spec.links:
            link = {"source": sc if l.source == "scenario" else l.source, "target": l.target}
            if l.link_type is not None:
                link["link_type"] = l.link_type
            links.append(link)
        ttl = build_scenario_ttl(
            spec.scenario_name, ctx.id, comps, links,
            service_name=spec.service_name, description=spec.description,
        )
    saved = None
    if spec.save:
        d = ws_root(ctx) / "scenarios"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_safe(spec.scenario_name)}.ttl"
        path.write_text(ttl, encoding="utf-8")
        saved = path.name
    return {"ttl": ttl, "chars": len(ttl), "saved": saved}
