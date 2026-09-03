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
    from backend.api_submission.connection import describe_endpoint, resolve_connection

    d = ws_root(ctx) / "services"
    out = []
    if d.exists():
        import yaml
        for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
            try:
                t = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                t = {}
            raw_conn = t.get("connection") or {}
            resolved = resolve_connection(raw_conn) if raw_conn else None
            out.append({
                "file": p.name,
                "service_name": t.get("service_name", p.stem),
                # Back-compat fields (env-expanded now, like the Streamlit tab).
                "url": (resolved or {}).get("url", ""),
                "method": (resolved or {}).get("method", "POST"),
                "transport": (resolved or {}).get("transport"),
                "endpoint": describe_endpoint(resolved) if resolved else "",
                # The raw block for the connection editor (unexpanded, so
                # ${VAR:-default} forms survive an edit round trip).
                "connection": raw_conn or None,
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
    """Convert a scenario to the service payload, and validate it the way the
    Streamlit tab does — against the raw (pre-clean) payload, so unresolved
    references are reported instead of silently stripped."""
    from dataclasses import asdict

    from backend.api_submission.ttl_converter import clean_placeholder_values, convert_scenario
    from backend.api_submission.validation import validate_payload

    template = _load_template(ctx, req.template_file)
    scen = ws_root(ctx) / "scenarios" / req.scenario_file
    if not scen.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        raw = convert_scenario(template, scen.read_text(encoding="utf-8"), clean=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}") from exc
    validation = validate_payload(raw, template, template.get("required_attributes"))
    payload = clean_placeholder_values(raw) or {}
    return {"payload": payload, "validation": asdict(validation)}


class SubmitReq(BaseModel):
    template_file: str
    payload: dict[str, Any]


@router.post("/submit")
def submit(req: SubmitReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Deliver the payload over the template's connection — the same transport
    layer (HTTP with auth/headers, or Redis streams) the Streamlit tab uses,
    with ${VAR:-default} expansion."""
    from backend.api_submission.connection import (
        describe_endpoint,
        resolve_connection,
        submit_via_connection,
    )

    template = _load_template(ctx, req.template_file)
    conn = template.get("connection") or {}
    resolved = resolve_connection(conn)
    if resolved["transport"] == "http" and not resolved["url"]:
        raise HTTPException(status_code=400, detail="Template has no connection.url.")
    tr = submit_via_connection(req.payload, conn)
    out: dict[str, Any] = {
        "ok": tr.success,
        "status_code": tr.status_code,
        "url": describe_endpoint(resolved),
        "response": tr.response_data,
    }
    if tr.error_message:
        out["error"] = tr.error_message
    if tr.request_id:
        out["request_id"] = tr.request_id
    return out


class TestReq(BaseModel):
    # Probe a saved template's connection, or an unsaved one from the editor.
    template_file: str | None = None
    connection: dict[str, Any] | None = None


@router.post("/test")
def test(req: TestReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Reachability probe: Redis PING, or an empty-body request where any
    status below 500 counts as reachable."""
    from backend.api_submission.connection import test_connection

    conn = req.connection
    if conn is None:
        if not req.template_file:
            raise HTTPException(status_code=400, detail="Pass template_file or connection.")
        conn = _load_template(ctx, req.template_file).get("connection") or {}
    return test_connection(conn)


class ConnectionReq(BaseModel):
    template_file: str
    connection: dict[str, Any]


@router.put("/connection")
def put_connection(req: ConnectionReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Write a connection block back into a service template — the REST
    equivalent of editing a registration in the Streamlit config tab. The rest
    of the template is preserved; the block is stored verbatim (unexpanded),
    so ${VAR:-default} forms keep working across deployments."""
    import yaml

    p = ws_root(ctx) / "services" / req.template_file
    if not p.exists() or not req.template_file.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=404, detail="service template not found")
    template = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    template["connection"] = req.connection
    p.write_text(yaml.safe_dump(template, sort_keys=False, default_flow_style=False),
                 encoding="utf-8")
    return {"file": req.template_file, "connection": req.connection}
