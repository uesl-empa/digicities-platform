"""Scenario Builder endpoints.

Pick component instances from the workspace into a scenario, then build the
scenario TTL with the platform's own ``build_scenario_ttl`` (usedInScenario +
ComponentLink edges) and save it under scenarios/.
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
    from apps.streamlit.components.component_explorer import (
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


class ScenComponent(BaseModel):
    uri: str
    type: str | None = None
    label: str | None = None


class ScenLink(BaseModel):
    source: str
    target: str


class ScenarioSpec(BaseModel):
    scenario_name: str
    components: list[ScenComponent] = []
    links: list[ScenLink] = []
    service_name: str | None = None
    description: str | None = None
    save: bool = True


@router.post("/build")
def build(spec: ScenarioSpec, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    if not spec.scenario_name.strip():
        raise HTTPException(status_code=400, detail="Give the scenario a name.")
    if not spec.components:
        raise HTTPException(status_code=400, detail="Add at least one component to the scenario.")

    from backend.scenario_builder import build_scenario_ttl

    comps = [{"uri": c.uri, "type": c.type, "label": c.label} for c in spec.components]
    links = [{"source": l.source, "target": l.target} for l in spec.links]
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
