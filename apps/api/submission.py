"""API Data Submission endpoints.

Pick a service template (services/*.yaml) + a scenario (scenarios/*.ttl), convert
the scenario to a model payload with ``convert_scenario`` (CL.X.Y link-walking),
and submit it to the service's connection endpoint.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, ws_root

router = APIRouter(prefix="/api/workspaces/{workspace_id}/submission", tags=["submission"])



def _load_template(ctx: WorkspaceContext, file: str) -> dict:
    import yaml
    p = ws_root(ctx) / "services" / file
    if not p.exists() or not file.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=404, detail="service template not found")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@router.get("/templates")
def templates(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    d = ws_root(ctx) / "services"
    out = []
    if d.exists():
        import yaml
        for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
            try:
                t = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                t = {}
            conn = t.get("connection") or {}
            out.append({
                "file": p.name,
                "service_name": t.get("service_name", p.stem),
                "url": conn.get("url", ""),
                "method": conn.get("method", "POST"),
            })
    return out


@router.get("/scenarios")
def scenarios(ctx: WorkspaceContext = Depends(get_ctx)) -> list[str]:
    d = ws_root(ctx) / "scenarios"
    return sorted(p.name for p in d.glob("*.ttl")) if d.exists() else []


class ConvertReq(BaseModel):
    template_file: str
    scenario_file: str


@router.post("/convert")
def convert(req: ConvertReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    template = _load_template(ctx, req.template_file)
    scen = ws_root(ctx) / "scenarios" / req.scenario_file
    if not scen.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    from backend.api_submission.ttl_converter import convert_scenario
    try:
        payload = convert_scenario(template, scen.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}") from exc
    return {"payload": payload}


class SubmitReq(BaseModel):
    template_file: str
    payload: dict[str, Any]


@router.post("/submit")
def submit(req: SubmitReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    template = _load_template(ctx, req.template_file)
    conn = template.get("connection") or {}
    url = conn.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Template has no connection.url.")
    method = (conn.get("method") or "POST").upper()
    timeout = float(conn.get("timeout", 60))
    import requests
    try:
        resp = requests.request(method, url, json=req.payload, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}
    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:4000]
    return {"ok": resp.ok, "status_code": resp.status_code, "url": url, "response": body}
