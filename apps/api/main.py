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

import os
import sys
from typing import Any

# Windows consoles default to a legacy codepage (cp1252); backend progress
# prints use emoji and must never crash a request over an un-encodable glyph.
# No-op on UTF-8 terminals/containers.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.workspace import WorkspaceContext, load_registry, ensure_workspace_repo

from .auth import require_auth
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

# Tag metadata shown as group headers in Swagger UI (/docs) and ReDoc
# (/redoc). Order here sets the display order.
openapi_tags = [
    {"name": "meta",
     "description": "Service liveness."},
    {"name": "workspaces",
     "description": "List, create, inspect and delete workspaces. A workspace "
                    "bundles one use case: its files, its ontology extension and "
                    "its graph. Every other group below is scoped under "
                    "`/api/workspaces/{workspace_id}`."},
    {"name": "graph",
     "description": "Provision the workspace graph (load its TTL with RDFS-plus "
                    "materialisation) and run SPARQL SELECT queries over it."},
    {"name": "explorer",
     "description": "Digital Replica Explorer reads: component types with "
                    "instance counts, and per-type instance/attribute tables "
                    "including catalogue-entry marking."},
    {"name": "queries",
     "description": "The workspace's saved SPARQL query library."},
    {"name": "ontology",
     "description": "Ontology Manager: inspect core and extension terms; author "
                    "extension components, attributes, links, categories, named "
                    "individuals and mappings; export and publish the extension "
                    "TTL."},
    {"name": "replica",
     "description": "Replica Builder: turn an Excel workbook (uploaded or built "
                    "in-app) into the workspace's replica TTL; read the current "
                    "TTL and project config."},
    {"name": "collections",
     "description": "Materialised sets and grouped sets over replica instances, "
                    "with aggregate stats."},
    {"name": "service",
     "description": "Service Requirements Builder: the component/attribute "
                    "palette a service can require, plus requirements TTL and "
                    "service-template YAML authoring."},
    {"name": "scenario",
     "description": "Scenario Builder: instance palette, saved scenarios, and "
                    "scenario TTL builds."},
    {"name": "submission",
     "description": "Convert a scenario into a service payload and submit it to "
                    "the service's endpoint."},
    {"name": "data-products",
     "description": "Processed data products (private and open): metadata, "
                    "components, and parsed resources (CSV, GeoJSON, EPW)."},
    {"name": "files",
     "description": "Read-only browsing of the workspace's files "
                    "(traversal-guarded, small files only)."},
    {"name": "agent",
     "description": "Onboarding-agent sessions: lifecycle, model selection, "
                    "file uploads, chat turns, and token streaming over SSE."},
]

app = FastAPI(
    title="Digicities API",
    version="0.1.0",
    description=(
        "HTTP access to the Digicities platform backend: the same functions the "
        "Streamlit app calls in-process, exposed for the React frontend "
        "(`digicities-frontend`) and any other client.\n\n"
        "Almost every route is scoped to a workspace via "
        "`/api/workspaces/{workspace_id}`; start with **workspaces** to find or "
        "create one.\n\n"
        "Authentication is off by default (open local mode). With "
        "`API_AUTH_ENABLED` set, every route requires an "
        "`Authorization: Bearer <token>` header (Keycloak token; see "
        "`apps/api/auth.py`)."
    ),
    openapi_tags=openapi_tags,
    # Optional bearer-token auth on every route — a no-op until
    # API_AUTH_ENABLED is set (see apps/api/auth.py). Reads the raw request
    # header, so the OpenAPI snapshot is unaffected.
    dependencies=[Depends(require_auth)],
)

# The React app is served from a different origin in dev. CORS_ORIGINS is a
# comma-separated allow-list of origins; the default "*" keeps dev open —
# set it to the deployed frontend origin(s) before this leaves a laptop.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
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

from .auth_local import router as auth_router, current_user_optional, auth_required  # noqa: E402
app.include_router(auth_router)


@app.on_event("startup")
def _start_workspace_cache() -> None:
    # Load the workspace registry into the in-memory cache and keep it fresh in the
    # background (also mirrors the catalog into the metadata DB). Requests then read
    # the cache instead of re-scanning the filesystem every time.
    from .registry_cache import start_background
    start_background()


# ── models ────────────────────────────────────────────────────────────────────
class WorkspaceSummary(BaseModel):
    id: str
    name: str
    graphdb_repository: str = ""
    description: str = ""
    updated_at: float | None = None  # epoch seconds; the landing page sorts by this
    created_date: str = ""  # "created_date" from workspace_meta/metadata.json (YYYY-MM-DD; often absent)
    protected: bool = False  # bundled demo — delete refuses these


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
def list_workspaces(user: dict | None = Depends(current_user_optional)) -> list[WorkspaceSummary]:
    """The workspaces the caller may see (their own + shared + granted), newest first.

    With no signed-in user (auth off) this is every workspace — unchanged behaviour.
    ``updated_at`` is the same activity-aware stamp the Streamlit landing page sorts by.
    """
    from backend.workspace import read_workspace_metadata, workspace_last_updated
    from backend.workspace.registry import BUNDLED_DEMO_IDS
    if user is None and auth_required():
        raise HTTPException(status_code=401, detail="Sign in to see your workspaces.")
    from backend.db import workspaces_repo
    from .deps import ws_root
    from .registry_cache import all_contexts
    allowed = workspaces_repo.visible_to(user["id"] if user else None)   # None = show all
    out = []
    for c in all_contexts():
        if allowed is not None and c.id not in allowed:
            continue
        root = ws_root(c)
        meta = read_workspace_metadata(c)
        out.append(WorkspaceSummary(
            id=c.id, name=c.name,
            graphdb_repository=c.graphdb_repository or "",
            description=c.description or "",
            updated_at=workspace_last_updated(root) if root.exists() else None,
            created_date=str(meta.get("created") or meta.get("created_date") or ""),
            protected=c.id in BUNDLED_DEMO_IDS,
        ))
    out.sort(key=lambda w: w.updated_at or 0, reverse=True)
    return out


class CreateWorkspace(BaseModel):
    name: str
    workspace_id: str = ""
    description: str = ""
    workspace_type: str = ""
    location: str = ""
    visibility: str = "private"        # 'private' (owner-only) | 'shared'


@app.post("/api/workspaces", response_model=WorkspaceSummary, tags=["workspaces"])
def create_workspace(body: CreateWorkspace,
                     user: dict | None = Depends(current_user_optional)) -> WorkspaceSummary:
    """Create a new local workspace (folder + graph dataset). A signed-in user becomes the
    owner and picks private/shared; with auth off it stays unowned + shared (as today)."""
    if user is None and auth_required():
        raise HTTPException(status_code=401, detail="Sign in to create a workspace.")
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
    try:                                    # so the new workspace is visible immediately
        from .registry_cache import refresh
        refresh()
        if user:                            # record ownership + chosen visibility
            from backend.db import workspaces_repo
            workspaces_repo.set_owner(ctx.id, user["id"], body.visibility)
    except Exception:
        pass
    return WorkspaceSummary(
        id=ctx.id, name=ctx.name,
        graphdb_repository=ctx.graphdb_repository or "",
        description=ctx.description or "",
    )


class ShareBody(BaseModel):
    email: str


@app.post("/api/workspaces/{workspace_id}/share", tags=["workspaces"])
def share_workspace(body: ShareBody, ctx: WorkspaceContext = Depends(get_ctx),
                    user: dict | None = Depends(current_user_optional)) -> dict[str, Any]:
    """Grant another user **editor** access to this workspace (owner-only)."""
    from backend.db import users_repo, workspaces_repo
    if not workspaces_repo.can_edit(ctx.id, user["id"] if user else None):
        raise HTTPException(status_code=403, detail="Only the owner can share this workspace.")
    target = users_repo.get_by_email(body.email)
    if not target:
        raise HTTPException(status_code=404, detail="No account with that email.")
    workspaces_repo.grant_editor(ctx.id, target["id"])
    return {"workspace_id": ctx.id, "granted_to": target["email"], "role": "editor"}


@app.get("/api/workspaces/{workspace_id}/info", tags=["workspaces"])
def workspace_info(ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Fuller workspace info for the sidebar panel (type/location/path/status)."""
    from backend.workspace import read_workspace_metadata, workspace_last_updated
    from .deps import ws_root
    root = ws_root(ctx)
    # Same reader the Streamlit landing page uses (backend.workspace.metadata),
    # so both frontends see identical metadata for a workspace.
    meta: dict[str, Any] = read_workspace_metadata(ctx)
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
    from backend.workspace import read_workspace_metadata, workspace_last_updated
    from backend.workspace.registry import BUNDLED_DEMO_IDS
    from .deps import ws_root
    root = ws_root(ctx)
    meta = read_workspace_metadata(ctx)
    return WorkspaceSummary(
        id=ctx.id, name=ctx.name,
        graphdb_repository=ctx.graphdb_repository or "",
        description=ctx.description or "",
        updated_at=workspace_last_updated(root) if root.exists() else None,
        created_date=str(meta.get("created") or meta.get("created_date") or ""),
        protected=ctx.id in BUNDLED_DEMO_IDS,
    )


@app.delete("/api/workspaces/{workspace_id}", tags=["workspaces"])
def delete_workspace(drop_dataset: bool = True,
                     ctx: WorkspaceContext = Depends(get_ctx)) -> dict[str, Any]:
    """Delete a workspace: its files, its triplestore dataset, its registration.

    Wraps ``backend.workspace.delete_workspace`` — the exact call behind the
    Streamlit landing page's danger zone. Bundled demos are refused (403).
    ``drop_dataset=false`` keeps the triplestore dataset (mirrors the
    Streamlit "keep the triplestore dataset" checkbox).
    """
    from backend.workspace import WorkspaceProtected, delete_workspace as _delete
    try:
        result = _delete(ctx.id, drop_dataset=drop_dataset, ctx=ctx)
    except WorkspaceProtected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not result.get("files_removed"):
        # Folder still on disk (e.g. a file is open in another program) —
        # surface it as a conflict so the client doesn't report success.
        raise HTTPException(
            status_code=409,
            detail=f"Could not remove the files of '{ctx.id}' — "
                   "they may be open in another program.",
        )
    return {"workspace": ctx.id, **result}


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
