"""Service Requirements Builder endpoints.

A service declares which component types + attributes + links a model requires.
The palette (available components and their attributes) is read with the same
functions the Explorer uses; the requirements TTL
(ComponentAttributeRequirement / ComponentComponentRequirement) is generated
here and saved to the workspace's services/.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client

router = APIRouter(prefix="/api/workspaces/{workspace_id}/service", tags=["service"])

_PREFIX = "https://digicities.info/proj"
_DICI = "dici_onto"


def _ws_root(ctx: WorkspaceContext) -> Path:
    return Path(os.getenv("USECASES_DIR", "/app/data/usecases")) / ctx.id


def _pascal(s: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", s) if w) or s


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
        f'\trdfs:label "{spec.label or spec.service_name}"@en .', "",
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


@router.post("/requirements")
def requirements(spec: ServiceSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    if not spec.service_name.strip():
        raise HTTPException(status_code=400, detail="Give the service a name.")
    ttl = _requirements_ttl(spec, ctx)
    saved = None
    if spec.save:
        sid = _pascal(spec.service_name)[:40] or "Service"
        sdir = _ws_root(ctx) / "services"
        sdir.mkdir(parents=True, exist_ok=True)
        path = sdir / f"{sid}.ttl"
        path.write_text(ttl, encoding="utf-8")
        saved = path.name
    return {"ttl": ttl, "chars": len(ttl), "saved": saved}
