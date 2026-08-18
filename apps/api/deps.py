"""Shared request dependencies for the Digicities REST API.

The platform's backend functions all take a ``WorkspaceContext`` (id + name +
storage + graphdb repository). The Streamlit app rebuilds that from
``st.session_state`` on every rerun; a stateless HTTP API instead resolves it
per request from the workspace registry, keyed by the ``{workspace_id}`` in the
route. This is the single seam every endpoint shares.
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import HTTPException, Path

from backend.workspace import WorkspaceContext, load_registry
from backend.graphdb.client import UnifiedGraphDBClient


def get_ctx(workspace_id: str = Path(..., description="workspace id")) -> WorkspaceContext:
    """Resolve a workspace's context from the registry, or 404.

    Mirrors what the Streamlit app holds in session state for the *open*
    workspace — but for any id, on demand.
    """
    ctx = load_registry().by_id(workspace_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_id}' not found")
    return ctx


def _graph_base_url() -> str:
    # Same resolution order the platform + agent use: explicit FUSEKI/GRAPHDB url,
    # else the in-network default. Set by docker-compose in the container.
    return os.getenv("FUSEKI_URL") or os.getenv("GRAPHDB_URL") or "http://localhost:3030"


@lru_cache(maxsize=16)
def _client_for(repo: str, base_url: str) -> UnifiedGraphDBClient:
    # Cached per (repo, url) so repeated queries reuse one authenticated session,
    # exactly as onboarding_agent/qa/tools.py does for the agent's Q&A.
    return UnifiedGraphDBClient(token="local", selected_repo=repo, base_url=base_url)


def graph_client(ctx: WorkspaceContext) -> UnifiedGraphDBClient:
    """A GraphDB/Fuseki client bound to this workspace's repository."""
    repo = ctx.graphdb_repository or ctx.id
    return _client_for(repo, _graph_base_url())
