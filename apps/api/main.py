"""Digicities REST API — an HTTP seam over the platform's in-process backend.

The platform's capabilities (provision a workspace's graph, build a replica,
build a scenario, query the graph, submit to a model) live as plain Python in
``backend.*`` and today are only reachable in-process from the Streamlit app.
This service exposes the same functions over HTTP so a separate front-end
(``digicities-frontend``, React) can drive them.

Round one deliberately covers only the paths the onboarding agent already
exercises headlessly — proof the backend runs without Streamlit. Run with::

    uvicorn apps.api.main:app --reload --port 8000

Endpoints that are fully wired to the backend are live; the remaining ones are
declared with the exact backend call they will wrap and return 501 until the
request/response contract is pinned down with the frontend.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.workspace import WorkspaceContext, load_registry, ensure_workspace_repo

from .deps import get_ctx, graph_client
from .explorer import router as explorer_router
from .queries import router as queries_router
from .ontology import router as ontology_router
from .replica import router as replica_router
from .collections import router as collections_router
from .service import router as service_router
from .scenario import router as scenario_router
from .submission import router as submission_router
from .agent import router as agent_router
from .data_products import router as data_products_router
from .files import router as files_router

app = FastAPI(
    title="Digicities API",
    version="0.1.0",
    description="HTTP access to the Digicities platform backend (round one: onboarding-agent paths).",
)

# The React app is served from a different origin in dev; open CORS here and
# tighten to the deployed frontend origin before this leaves a laptop.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(explorer_router)
app.include_router(queries_router)
app.include_router(ontology_router)
app.include_router(replica_router)
app.include_router(collections_router)
app.include_router(service_router)
app.include_router(scenario_router)
app.include_router(submission_router)
app.include_router(agent_router)
app.include_router(data_products_router)
app.include_router(files_router)


# ── models ────────────────────────────────────────────────────────────────────
class WorkspaceSummary(BaseModel):
    id: str
    name: str
    graphdb_repository: str = ""
    description: str = ""
    updated_at: float | None = None  # epoch seconds; the landing page sorts by this


class QueryRequest(BaseModel):
    query: str
    infer: bool = True


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    count: int


# ── meta ──────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/workspaces", response_model=list[WorkspaceSummary], tags=["workspaces"])
def list_workspaces() -> list[WorkspaceSummary]:
    """Every workspace the platform can see (local + discovered), newest first.

    ``updated_at`` is the same activity-aware stamp the Streamlit landing page
    sorts by (``backend.workspace.workspace_last_updated``).
    """
    from backend.workspace import workspace_last_updated
    from .deps import ws_root
    out = []
    for c in load_registry():
        root = ws_root(c)
        out.append(WorkspaceSummary(
            id=c.id, name=c.name,
            graphdb_repository=c.graphdb_repository or "",
            description=c.description or "",
            updated_at=workspace_last_updated(root) if root.exists() else None,
        ))
    out.sort(key=lambda w: w.updated_at or 0, reverse=True)
    return out


class CreateWorkspace(BaseModel):
    name: str
    workspace_id: str = ""
    description: str = ""
    workspace_type: str = ""
    location: str = ""


@app.post("/api/workspaces", response_model=WorkspaceSummary, tags=["workspaces"])
def create_workspace(body: CreateWorkspace) -> WorkspaceSummary:
    """Create a new local workspace (folder + graph dataset)."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Workspace name is required.")
    from backend.workspace import create_workspace as _create
    try:
        ctx = _create(
            body.name.strip(),
            workspace_id=body.workspace_id.strip() or None,
            description=body.description,
            workspace_type=body.workspace_type,
            location=body.location,
            provision_graph=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Create failed: {exc}") from exc
    return WorkspaceSummary(
        id=ctx.id, name=ctx.name,
        graphdb_repository=ctx.graphdb_repository or "",
        description=ctx.description or "",
    )


@app.get("/api/workspaces/{workspace_id}/info", tags=["workspaces"])
def workspace_info(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Fuller workspace info for the sidebar panel (type/location/path/status)."""
    import json
    from backend.workspace import workspace_last_updated
    from .deps import ws_root
    root = ws_root(ctx)
    meta: dict[str, Any] = {}
    mp = root / "workspace_meta" / "metadata.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return {
        "name": ctx.name,
        "id": ctx.id,
        "type": meta.get("type", ""),
        "location": meta.get("location", ""),
        "user": "local_user",
        "path": str(root) if root.exists() else None,
        "repository": ctx.graphdb_repository or ctx.id,
        "description": ctx.description or meta.get("description", ""),
        "nextcloud": False,
        "triplestore": True,
        "updated_at": workspace_last_updated(root) if root.exists() else None,
    }


@app.get("/api/workspaces/{workspace_id}", response_model=WorkspaceSummary, tags=["workspaces"])
def get_workspace(ctx: WorkspaceContext = Depends(get_ctx)) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=ctx.id, name=ctx.name,
        graphdb_repository=ctx.graphdb_repository or "",
        description=ctx.description or "",
    )


# ── provision (load + materialise the workspace graph) ─────────────────────────
@app.post("/api/workspaces/{workspace_id}/provision", tags=["graph"])
def provision(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Load the workspace's TTL into its graph with RDFS-plus materialisation.

    Wraps ``backend.workspace.ensure_workspace_repo`` — the exact call the
    Streamlit app makes on workspace open and the agent makes after a build.
    """
    ok = ensure_workspace_repo(ctx)
    return {"workspace": ctx.id, "provisioned": bool(ok)}


# ── query the graph ────────────────────────────────────────────────────────────
@app.post("/api/workspaces/{workspace_id}/query", response_model=QueryResponse, tags=["graph"])
def query(req: QueryRequest, ctx: WorkspaceContext = Depends(get_ctx)) -> QueryResponse:
    """Run a SPARQL SELECT over the workspace's named graphs.

    Wraps ``UnifiedGraphDBClient.sparql_api_query`` — the same client the
    agent's Q&A uses.
    """
    client = graph_client(ctx)
    try:
        df = client.sparql_api_query(req.query, infer=req.infer, out_format="df")
    except Exception as exc:  # surface the store's error rather than a bare 500
        raise HTTPException(status_code=400, detail=f"query failed: {exc}") from exc
    if df is None or getattr(df, "empty", True):
        return QueryResponse(columns=[], rows=[], count=0)
    cols = [str(c) for c in df.columns]
    rows = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    return QueryResponse(columns=cols, rows=rows, count=len(rows))
