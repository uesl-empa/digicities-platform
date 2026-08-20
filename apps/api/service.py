"""Service Requirements Builder endpoints.

A service declares which component types + attributes + links a model requires.
The palette (available components and their attributes) is read with the same
functions the Explorer uses; the requirements TTL
(ComponentAttributeRequirement / ComponentComponentRequirement) is generated
here and saved to the workspace's services/.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client, ws_root

router = APIRouter(prefix="/api/workspaces/{workspace_id}/service", tags=["service"])

_PREFIX = "https://digicities.info/proj"
_DICI = "dici_onto"


def _pascal(s: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", s) if w) or s


def _ttl_str(s: str) -> str:
    """Escape a user-supplied string for a quoted Turtle literal — an unescaped
    quote or backslash in a label would break (or worse, rewrite) the document."""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r"))


@router.get("/palette")
def palette(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Component types and their attributes — what a service can require."""
    from apps.streamlit.components.component_explorer import (
        get_component_types_with_instances,
        get_component_data_unified,
        process_enhanced_component_data,
        get_visible_columns,
    )

    client = graph_client(ctx)
    types = get_component_types_with_instances(client)
    if types is None or types.empty:
        return []
    out: list[dict[str, Any]] = []
    for r in types.itertuples():
        name = str(r.componentName)
        instances, attrs = get_component_data_unified(client, name)
        cols: list[str] = []
        if instances:
            df = process_enhanced_component_data(instances, attrs)
            cols = [c for c in get_visible_columns(df) if c not in ("URI", "instance_id", "label")
                    and not c.startswith("_")]
        out.append({"component": name, "class": str(r.componentType), "attributes": cols})
    return out


class Requirement(BaseModel):
    component: str          # PascalCase class name
    attributes: list[str] = []


class Link(BaseModel):
    domain: str
    range: str


class ServiceSpec(BaseModel):
    service_name: str
    label: str = ""
    requirements: list[Requirement] = []
    links: list[Link] = []
    save: bool = True


def _requirements_ttl(spec: ServiceSpec, ctx: WorkspaceContext) -> str:
    sid = _pascal(spec.service_name)[:40] or "Service"
    base = f"{_PREFIX}/{ctx.id}/services/"
    L = [
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", "",
        f"<{base}{sid}> a dici_onto:Service ;",
        f'\trdfs:label "{_ttl_str(spec.label or spec.service_name)}"@en .', "",
    ]
    n = 0
    for req in spec.requirements:
        comp = _pascal(req.component)
        for attr in req.attributes:
            n += 1
            L += [f"<{base}req_{n}> a dici_onto:ComponentAttributeRequirement ;",
                  f"\t{_DICI}:isRequiredBy <{base}{sid}> ;",
                  f"\t{_DICI}:hasInputEntity {_DICI}:{comp} ;",
                  f"\t{_DICI}:hasInputAttribute {_DICI}:{attr} ;",
                  f'\trdfs:label "{comp}.{attr} required"@en .', ""]
    for lk in spec.links:
        n += 1
        L += [f"<{base}req_{n}> a dici_onto:ComponentComponentRequirement ;",
              f"\t{_DICI}:isRequiredBy <{base}{sid}> ;",
              f"\t{_DICI}:hasInputEntity {_DICI}:{_pascal(lk.domain)}, {_DICI}:{_pascal(lk.range)} ;",
              f'\trdfs:label "{_pascal(lk.domain)} linked to {_pascal(lk.range)}"@en .', ""]
    return "\n".join(L) + "\n"


class SvcEntry(BaseModel):
    component_type: str
    parent: str | None = None
    attributes: list[str] = []


class TemplateSpec(BaseModel):
    service_name: str
    description: str = ""
    connection: dict[str, Any] | None = None
    entries: list[SvcEntry]
    save: bool = True


def _camel(s: str) -> str:
    p = _pascal(s)
    return p[:1].lower() + p[1:] if p else s


def _scenario_data(entries: list[SvcEntry]) -> dict[str, Any]:
    """Nested scenario_data mirroring the shipped service templates: level-1 roots
    carry name/uri + attributes; children are {link: CL.Parent.Child, template: {...}}."""
    def node(entry: SvcEntry, is_root: bool) -> dict[str, Any]:
        t = _pascal(entry.component_type)
        if is_root:
            s: dict[str, Any] = {"name": f"{t}.label", "uri": f"{t}.URI"}
            body = s
        else:
            parent = _pascal(entry.parent or "")
            s = {"link": f"CL.{parent}.{t}", "template": {"uri": f"{t}.URI"}}
            body = s["template"]
        for a in entry.attributes:
            if a == "label":
                if not is_root:
                    body["label"] = f"{t}.label"
                continue
            body[a] = f"{t}.{a}"
        for child in [e for e in entries if _pascal(e.parent or "") == t]:
            body[_camel(child.component_type)] = node(child, False)
        return s

    sd: dict[str, Any] = {"uri": "Scenario.URI", "label": "Scenario.label"}
    for root in [e for e in entries if not e.parent]:
        sd[_camel(root.component_type)] = node(root, True)
    return sd


@router.post("/template")
def template(spec: TemplateSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Generate the service-template YAML (connection + nested scenario_data)."""
    import yaml
    if not spec.service_name.strip():
        raise HTTPException(status_code=400, detail="Give the service a name.")
    doc: dict[str, Any] = {"service_name": spec.service_name}
    if spec.description:
        doc["description"] = spec.description
    if spec.connection:
        doc["connection"] = spec.connection
    doc["scenario_data"] = _scenario_data(spec.entries)
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    saved = None
    if spec.save:
        sid = _pascal(spec.service_name)[:40] or "Service"
        sdir = ws_root(ctx) / "services"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / f"{sid}.yaml").write_text(text, encoding="utf-8")
        saved = f"{sid}.yaml"
    return {"yaml": text, "saved": saved}


@router.post("/requirements")
def requirements(spec: ServiceSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    if not spec.service_name.strip():
        raise HTTPException(status_code=400, detail="Give the service a name.")
    ttl = _requirements_ttl(spec, ctx)
    saved = None
    if spec.save:
        sid = _pascal(spec.service_name)[:40] or "Service"
        sdir = ws_root(ctx) / "services"
        sdir.mkdir(parents=True, exist_ok=True)
        path = sdir / f"{sid}.ttl"
        path.write_text(ttl, encoding="utf-8")
        saved = path.name
    return {"ttl": ttl, "chars": len(ttl), "saved": saved}
