"""API Data Submission endpoints.

Pick a service template (services/*.yaml) + a scenario (scenarios/*.ttl), convert
the scenario to a model payload with ``convert_scenario`` (CL.X.Y link-walking),
and submit it to the service's connection endpoint.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.workspace import WorkspaceContext

from .deps import get_ctx, graph_client, ws_root

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
def scenarios(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Saved scenarios with the service each was built for (builtForService),
    so the submit UI can scope scenarios to the selected service the way the
    Streamlit tab does — a scenario built for another service can't be
    submitted to the wrong one."""
    d = ws_root(ctx) / "scenarios"
    out: list[dict[str, Any]] = []
    if d.exists():
        for p in sorted(d.glob("*.ttl")):
            service = None
            try:
                m = re.search(r'builtForService\s+"((?:[^"\\]|\\.)*)"',
                              p.read_text(encoding="utf-8"))
                if m:
                    service = m.group(1)
            except Exception:
                pass
            out.append({"file": p.name, "service": service})
    return out


class ConvertReq(BaseModel):
    template_file: str
    scenario_file: str


@router.post("/convert")
def convert(req: ConvertReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Convert a scenario to the service payload, and validate it the way the
    Streamlit tab does — against the raw (pre-clean) payload, so unresolved
    references are reported instead of silently stripped."""
    from dataclasses import asdict

    from backend.api_submission.materialize import materialize_against_workspace
    from backend.api_submission.ttl_converter import clean_placeholder_values, convert_scenario
    from backend.api_submission.validation import validate_payload

    template = _load_template(ctx, req.template_file)
    scen = ws_root(ctx) / "scenarios" / req.scenario_file
    if not scen.exists():
        raise HTTPException(status_code=404, detail="scenario not found")
    # Thin scenarios reference the replica without carrying values — merge
    # them first, like the Streamlit Convert tab and the agent do.
    try:
        client = graph_client(ctx)
    except Exception:
        client = None
    ttl_text = materialize_against_workspace(getattr(ctx, "storage", None),
                                             scen.read_text(encoding="utf-8"), client)
    try:
        raw = convert_scenario(template, ttl_text, clean=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}") from exc
    validation = validate_payload(raw, template, template.get("required_attributes"))
    payload = clean_placeholder_values(raw) or {}
    return {"payload": payload, "validation": asdict(validation)}


class SubmitReq(BaseModel):
    template_file: str
    payload: dict[str, Any]
    # When the scenario is named, the result is persisted under results/
    # (like the Streamlit results viewer); pass persist=False to skip.
    scenario_file: str | None = None
    persist: bool = True


@router.post("/submit")
def submit(req: SubmitReq, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Deliver the payload over the template's connection — the same transport
    layer (HTTP with auth/headers, or Redis streams) the Streamlit tab uses,
    with ${VAR:-default} expansion. Successful or not, the outcome can be
    persisted under results/<service>/ for the Past Results view."""
    import json
    from datetime import datetime

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
    # The payload's service_name must match the service actually submitted to
    # (Streamlit stamps it the same way before submitting).
    payload = dict(req.payload)
    if "service_name" in payload and template.get("service_name"):
        payload["service_name"] = template["service_name"]
    tr = submit_via_connection(payload, conn)

    # Best-effort follow-up: pull the full result from the service's results
    # endpoint so the persisted record is complete, not just the summary.
    scenario_id = (tr.response_data or {}).get("scenario_id") if isinstance(tr.response_data, dict) else None
    if tr.success and scenario_id and resolved["transport"] == "http" and resolved["url"]:
        try:
            import requests

            dr = requests.get(f"{resolved['url'].rstrip('/')}/results/{scenario_id}", timeout=15)
            if dr.status_code == 200:
                tr.response_data = {**(tr.response_data or {}), "result_detail": dr.json()}
        except Exception:
            pass

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

    if req.persist:
        service_name = str(template.get("service_name") or req.template_file.rsplit(".", 1)[0])
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        scen = (req.scenario_file or "payload").rsplit(".", 1)[0]
        d = ws_root(ctx) / "results" / re.sub(r"[^A-Za-z0-9_.\-]", "_", service_name)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "metadata": {"service_name": service_name, "scenario_name": scen,
                         "timestamp": stamp, "success": tr.success,
                         "status_code": tr.status_code},
            "submission": {"endpoint": out["url"], "request_id": tr.request_id or None},
            "submitted_data": payload,
            "response": tr.response_data,
            "error": tr.error_message or None,
        }
        f = d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', scen)}_{stamp}.json"
        f.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        out["saved"] = str(f.relative_to(ws_root(ctx))).replace("\\", "/")
    return out


@router.get("/results")
def results(ctx: WorkspaceContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Persisted submission results (newest first), from results/<service>/."""
    import json

    root = ws_root(ctx) / "results"
    out: list[dict[str, Any]] = []
    if root.exists():
        for p in root.glob("*/*.json"):
            entry: dict[str, Any] = {
                "file": str(p.relative_to(ws_root(ctx))).replace("\\", "/"),
                "service": p.parent.name,
            }
            try:
                meta = (json.loads(p.read_text(encoding="utf-8")) or {}).get("metadata", {})
                entry.update({k: meta.get(k) for k in
                              ("service_name", "scenario_name", "timestamp", "success", "status_code")})
            except Exception:
                pass
            out.append(entry)
    out.sort(key=lambda e: str(e.get("timestamp") or e["file"]), reverse=True)
    return out


@router.get("/results/content")
def result_content(file: str, ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """One persisted result, as saved."""
    import json

    root = (ws_root(ctx) / "results").resolve()
    p = (ws_root(ctx) / file).resolve()
    # The file param must stay inside results/ — no path traversal.
    if root not in p.parents or not p.name.endswith(".json") or not p.exists():
        raise HTTPException(status_code=404, detail="result not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="result file is not valid JSON")


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
