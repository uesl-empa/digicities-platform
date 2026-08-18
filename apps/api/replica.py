"""Replica Builder endpoints — the reusable path: a digital-replica workbook
(.xlsx) to instance TTL via the platform's own converter, plus reading back the
workspace's current replica TTL for Preview & Export.

The in-app Instances/Attributes/Links editor (session-coupled TTL generation)
is a later chunk; this covers Excel Import + Preview & Export + config.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.workspace import WorkspaceContext

from .deps import get_ctx

router = APIRouter(prefix="/api/workspaces/{workspace_id}/replica", tags=["replica"])

_PROJECT_PREFIX = "https://digicities.info/proj"


def _ws_root(ctx: WorkspaceContext) -> Path:
    return Path(os.getenv("USECASES_DIR", "/app/data/usecases")) / ctx.id


def _project_uri(ctx: WorkspaceContext) -> str:
    return f"{_PROJECT_PREFIX}/{ctx.id}"


@router.get("/config")
def config(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, str]:
    return {"workspace": ctx.id, "project_uri": _project_uri(ctx)}


@router.get("/ttl")
def replica_ttl(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """The workspace's current replica TTL (Preview & Export)."""
    out = _ws_root(ctx) / "ingestion" / "output"
    files = sorted(out.glob("*.ttl")) if out.exists() else []
    if not files:
        return {"ttl": "", "file": None}
    f = files[0]
    return {"ttl": f.read_text(encoding="utf-8"), "file": f.name}


@router.post("/import")
async def import_workbook(
    file: UploadFile = File(...),
    ctx: WorkspaceContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Convert an uploaded digital-replica workbook (.xlsx) to instance TTL via
    ``process_excel_to_ttl`` and persist it to the workspace's ingestion output."""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload a .xlsx digital-replica workbook.")

    root = _ws_root(ctx)
    in_dir = root / "ingestion" / "input"
    out_dir = root / "ingestion" / "output"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    xlsx_path = in_dir / file.filename
    xlsx_path.write_bytes(await file.read())
    ttl_path = out_dir / f"{ctx.id}.ttl"

    from backend.replica_builder.utils.create_class_and_attribute_graph import process_excel_to_ttl

    try:
        process_excel_to_ttl(_project_uri(ctx), str(xlsx_path), str(ttl_path), uri_mode="default")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}") from exc

    ttl = ttl_path.read_text(encoding="utf-8") if ttl_path.exists() else ""
    return {"file": ttl_path.name, "triples_preview": ttl[:4000], "ttl": ttl, "chars": len(ttl)}
