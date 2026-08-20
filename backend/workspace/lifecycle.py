# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Workspace-open orchestration, headless.

Opening a workspace is: registry lookup → lazy triplestore provisioning →
graph-client creation. That sequence used to live inline in the Streamlit
app's ``open_workspace``; it now lives here so any frontend (Streamlit, the
REST API, scripts) opens a workspace the same way. The Streamlit shell keeps
only the session parking / per-workspace state reset around a call to
:func:`open_workspace`.

The graph client is created through a ``client_factory`` so the Streamlit
shell can inject its UI-aware ``GraphDBClient`` subclass (error banners +
token refresh) while headless callers get the plain backend client.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .context import WorkspaceContext
from .graphdb_provisioning import ensure_workspace_repo
from .registry import load_registry

# A client factory takes (token=..., selected_repo=...) and returns a
# GraphDB/Fuseki client. Defaults to the backend client.
ClientFactory = Callable[..., object]

CONNECTION_TEST_QUERY = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"


def _default_client_factory(**kwargs):
    from backend.graphdb.client import GraphDBClient
    return GraphDBClient(**kwargs)


def build_graph_client(
    token: Optional[str],
    repo: str,
    client_factory: Optional[ClientFactory] = None,
):
    """Create a graph client bound to ``repo``. Raises on failure."""
    factory = client_factory or _default_client_factory
    return factory(token=token, selected_repo=repo)


def check_connection(client) -> bool:
    """True when ``client`` answers a trivial SPARQL query with HTTP 200.

    Never raises — any failure (no client, transport error, non-200) is False.
    Callers own their own caching (the Streamlit shell keeps a 30 s
    session-state cache around this).
    """
    if client is None:
        return False
    try:
        result = client.sparql_api_query(CONNECTION_TEST_QUERY, out_format="response")
        return bool(result is not None and result.status_code == 200)
    except Exception:
        return False


@dataclass
class OpenedWorkspace:
    """Result of :func:`open_workspace` — everything the caller needs to park.

    - ``ctx``             : the resolved WorkspaceContext, or None when the id
                            isn't in the registry (legacy / NextCloud-group ids)
    - ``graphdb_repository``: the repo the client is bound to (ctx's repo, else
                            the workspace id)
    - ``client``          : the graph client, or None when creation failed
    - ``provisioned``     : True when ``ensure_workspace_repo`` reported success
    - ``provision_error`` : provisioning failure message (non-fatal — file-based
                            modules still work without the triplestore)
    - ``client_error``    : client-creation failure message
    """
    workspace_id: str
    ctx: Optional[WorkspaceContext] = None
    graphdb_repository: str = ""
    client: object = None
    provisioned: bool = False
    provision_error: Optional[str] = None
    client_error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.graphdb_repository:
            self.graphdb_repository = self.workspace_id

    @property
    def connected(self) -> bool:
        return self.client is not None


def open_workspace(
    workspace_id: str,
    token: Optional[str] = None,
    client_factory: Optional[ClientFactory] = None,
    provision: bool = True,
) -> OpenedWorkspace:
    """Open a workspace: resolve its context, ensure its repo, build a client.

    Never raises — every failure mode is reported on the returned
    :class:`OpenedWorkspace` so the caller decides how loudly to surface it:

    - Registry lookup failure ⇒ ``ctx`` is None and the client is still built
      against ``workspace_id`` (pre-registry behaviour).
    - Provisioning failure ⇒ ``provision_error`` set; non-fatal by design —
      the UI works without the triplestore and the user can create the repo
      manually.
    - Client-creation failure ⇒ ``client`` None + ``client_error`` set.

    Provisioning is idempotent: re-uploading the workspace's current TTLs on
    every open keeps the triplestore in sync with file edits.
    """
    result = OpenedWorkspace(workspace_id=workspace_id)

    try:
        result.ctx = load_registry().by_id(workspace_id)
    except Exception as exc:
        print(f"[open_workspace] registry lookup failed for {workspace_id}: {exc}")

    if result.ctx is not None:
        result.graphdb_repository = result.ctx.graphdb_repository or workspace_id
        if provision:
            try:
                result.provisioned = bool(ensure_workspace_repo(result.ctx))
            except Exception as exc:
                result.provision_error = str(exc)

    try:
        result.client = build_graph_client(
            token, result.graphdb_repository, client_factory=client_factory)
    except Exception as exc:
        result.client_error = str(exc)

    return result
