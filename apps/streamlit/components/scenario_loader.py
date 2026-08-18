# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Shared "load existing scenario" picker.

One UI used by the Scenario Builder, the Assumptions module and the API
submission converter so a scenario can be loaded from the same three sources
everywhere:

  - Workspace files  : ``scenarios/*.ttl`` in the active workspace storage.
  - Knowledge graph  : scenarios stored in the ``<http://scenarios>`` named graph.
  - Upload           : a TTL file from the user's machine.

The picker only reads; it returns the resolved scenario(s) as
``[{'name', 'content', 'source', 'uri'}]`` for the current selection and writes
no module-specific session state. Each caller decides what to do with the
returned TTL (convert it, parse it into editable components, etc.).

Pass a unique ``key_prefix`` per caller so widget keys don't collide when more
than one loader is mounted in the same session.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import streamlit as st

# The scenario triple that records which service template a scenario was built
# for (e.g. dici_onto:builtForService "FlexibilityOptimizer").
_SERVICE_RE = re.compile(r'builtForService\s+"([^"]+)"')


def _declared_service(ttl_text: str) -> Optional[str]:
    """The service a scenario TTL declares it was built for, or None."""
    m = _SERVICE_RE.search(ttl_text or "")
    return m.group(1) if m else None


def _materialize_against_workspace(storage, scenario_text: str, client=None) -> str:
    """Merge a scenario with the workspace's replica (ingestion/output) so a
    scenario that references canonical components + overrides becomes a
    self-contained payload. Returns the original text on any problem (or when the
    text isn't a scenario / has no replica to merge).

    When a graph client is available, the workspace's DERIVED collections graph
    is merged in too — projected aggregate attributes (e.g. a District's
    FloorAreaMean) then ride along with the replica attributes, so a service
    template can request them as ordinary Component.attribute references."""
    try:
        from rdflib import Graph
        from rdflib.namespace import RDF
        from backend.graphdb.queries.scenarios import materialize_scenario_graphs, _DICI

        scn = Graph()
        scn.parse(data=scenario_text, format="turtle")
        scenarios = list(scn.subjects(RDF.type, _DICI.Scenario))
        if not scenarios:
            return scenario_text

        rep = Graph()
        try:
            if storage is not None and storage.exists("ingestion/output"):
                for rel in storage.glob("ingestion/output/*.ttl"):
                    try:
                        rep.parse(data=storage.read_text(rel), format="turtle")
                    except Exception:
                        pass
        except Exception:
            pass

        # Derived collections (projected aggregates) live only in the graph —
        # fetch the named graph via the graph-store endpoint (typed Turtle,
        # same channel provisioning writes through).
        try:
            client = client or st.session_state.get("workspace_client")
            if client is not None and getattr(client, "repository", None):
                import requests
                from backend.graphdb.graphs import COLLECTIONS_GRAPH
                from backend.triplestore import get_backend
                backend = get_backend()
                r = requests.get(
                    backend.graph_store_url(client.repository, COLLECTIONS_GRAPH),
                    headers={"Accept": "text/turtle"},
                    auth=getattr(backend, "auth", None), timeout=30)
                if r.status_code == 200 and r.text.strip():
                    rep.parse(data=r.text, format="turtle")
        except Exception:
            pass                      # collections are optional enrichment

        materialized = materialize_scenario_graphs(scn, rep, str(scenarios[0]))
        return materialized or scenario_text
    except Exception:
        return scenario_text


def _service_allows(declared: Optional[str], wanted: Optional[str],
                    include_unlabelled: bool = False) -> bool:
    """Whether a scenario passes the service filter.

    With no service chosen, everything passes. Otherwise the scenario must have
    been built for the chosen service (``builtForService``). A scenario that
    declares no service passes only when ``include_unlabelled`` is set - so a
    scenario can't be sent to the wrong service by default."""
    if not wanted:
        return True
    if declared == wanted:
        return True
    if declared is None:
        return include_unlabelled
    return False


def _workspace_storage():
    ctx = st.session_state.get("workspace_context")
    return getattr(ctx, "storage", None) if ctx is not None else None


def _available_sources(client) -> List[str]:
    sources = []
    if _workspace_storage() is not None:
        sources.append("workspace")
    if (client or st.session_state.get("workspace_client")) is not None:
        sources.append("graph")
    sources.append("upload")
    return sources


def _load_from_workspace(key_prefix: str, allow_multiple: bool,
                         service: Optional[str] = None,
                         include_unlabelled: bool = False) -> List[Dict]:
    storage = _workspace_storage()
    if storage is None:
        st.error("❌ No active workspace storage. Open a workspace first.")
        return []

    folder = "scenarios"
    try:
        rels = storage.glob(f"{folder}/*.ttl") if storage.exists(folder) else []
    except Exception as e:
        st.error(f"❌ Could not list workspace scenarios: {e}")
        return []

    # Read each scenario and keep those allowed by the service filter.
    contents: Dict[str, str] = {}
    for rel in rels:
        fname = rel.rsplit("/", 1)[-1]
        try:
            text = storage.read_text(rel)
        except Exception:
            continue
        if _service_allows(_declared_service(text), service, include_unlabelled):
            contents[fname] = text

    files = sorted(contents)
    if not files:
        if service:
            st.info(f"ℹ️ No scenarios built for **{service}** in this workspace's `scenarios/` folder.")
        else:
            st.info("ℹ️ No scenario files in this workspace's `scenarios/` folder.")
        st.caption("💡 Build one in the Scenario Builder, or upload a TTL file.")
        return []

    label = lambda f: f[:-4].replace("_", " ") if f.endswith(".ttl") else f
    if allow_multiple:
        chosen = st.multiselect("Scenario files:", files, format_func=label,
                                key=f"{key_prefix}_ws_sel")
    else:
        one = st.selectbox("Scenario file:", files, format_func=label,
                           key=f"{key_prefix}_ws_sel")
        chosen = [one] if one else []

    return [{"name": f[:-4] if f.endswith(".ttl") else f,
             "content": _materialize_against_workspace(storage, contents[f]),
             "source": "workspace", "uri": None}
            for f in chosen]


def _load_from_graph(client, key_prefix: str, allow_multiple: bool,
                     service: Optional[str] = None,
                     include_unlabelled: bool = False) -> List[Dict]:
    client = client or st.session_state.get("workspace_client")
    if client is None:
        st.error("❌ No graph connection. Open a workspace first.")
        return []

    try:
        from backend.graphdb.queries.scenarios import list_scenarios, construct_scenario_ttl
    except Exception as e:
        st.error(f"❌ Scenario queries unavailable: {e}")
        return []

    df = list_scenarios(client)
    if df is None or df.empty:
        st.info("ℹ️ No scenarios found in the knowledge graph for this workspace.")
        st.caption("💡 Scenarios appear here once a workspace with saved scenarios is (re)opened.")
        return []

    # Map a display label -> scenario URI, applying the service filter.
    options = {}
    for _, row in df.iterrows():
        uri = str(row.get("scenario") or "").strip()
        if not uri:
            continue
        raw = row.get("service")
        declared = str(raw).strip() if raw is not None else ""
        if declared.lower() in ("", "nan", "none"):
            declared = None
        if not _service_allows(declared, service, include_unlabelled):
            continue
        lbl = str(row.get("label") or "").strip() or uri.rsplit("/", 1)[-1]
        options[f"{lbl}  ·  {uri.rsplit('/', 1)[-1]}"] = uri

    if not options:
        if service:
            st.info(f"ℹ️ No scenarios built for **{service}** in the knowledge graph.")
        else:
            st.info("ℹ️ No scenarios found in the knowledge graph.")
        return []

    keys = list(options.keys())
    if allow_multiple:
        picked = st.multiselect("Scenarios in the graph:", keys, key=f"{key_prefix}_kg_sel")
    else:
        one = st.selectbox("Scenario in the graph:", keys, key=f"{key_prefix}_kg_sel")
        picked = [one] if one else []

    out = []
    for disp in picked:
        uri = options[disp]
        try:
            content = construct_scenario_ttl(client, uri)
        except Exception as e:
            st.warning(f"⚠️ Could not load scenario from graph: {e}")
            content = None
        if content:
            out.append({"name": uri.rsplit("/", 1)[-1], "content": content,
                        "source": "graph", "uri": uri})
        else:
            st.warning(f"⚠️ Scenario '{disp}' could not be reconstructed from the graph.")
    return out


def _load_from_upload(key_prefix: str, allow_multiple: bool) -> List[Dict]:
    uploaded = st.file_uploader("Choose TTL file(s):", type=["ttl"],
                                accept_multiple_files=allow_multiple,
                                key=f"{key_prefix}_upload")
    if not uploaded:
        return []
    items = uploaded if isinstance(uploaded, list) else [uploaded]
    out = []
    for f in items:
        try:
            content = f.getvalue().decode("utf-8")
            out.append({"name": f.name[:-4] if f.name.endswith(".ttl") else f.name,
                        "content": content, "source": "upload", "uri": None})
        except Exception as e:
            st.warning(f"⚠️ Could not read {f.name}: {e}")
    return out


def render_scenario_loader(client=None, sources=("workspace", "graph", "upload"),
                           key_prefix: str = "scenario_loader",
                           allow_multiple: bool = False,
                           show_preview: bool = True,
                           service: Optional[str] = None) -> List[Dict]:
    """Render the scenario source picker and return the current selection.

    Args:
        client: a GraphDB client for the graph source (falls back to
            ``st.session_state.workspace_client``).
        sources: which sources to offer, in order; unavailable ones are dropped.
        key_prefix: unique prefix for widget keys (one per caller).
        allow_multiple: allow selecting more than one scenario.
        show_preview: show a collapsible TTL preview of the selection.
        service: when set, restrict workspace/graph scenarios to those built for
            this service (via the ``builtForService`` triple); scenarios that
            declare no service are still shown. Upload is never filtered.

    Returns:
        A list of ``{'name', 'content', 'source', 'uri'}`` for the current
        selection (empty if nothing is selected).
    """
    available = [s for s in sources if s in _available_sources(client)]
    if not available:
        st.warning("⚠️ No scenario sources available. Open a workspace first.")
        return []

    include_unlabelled = False
    if service:
        include_unlabelled = st.checkbox(
            "Also show scenarios with no declared service",
            value=False, key=f"{key_prefix}_incl_unlabelled",
            help="By default only scenarios built for this service are shown, so a "
                 "scenario can't be sent to the wrong service. Tick to also include "
                 "scenarios that declare no service.",
        )
        if include_unlabelled:
            st.caption(f"Showing scenarios built for **{service}**, plus unlabelled scenarios.")
        else:
            st.caption(f"Showing only scenarios built for **{service}**.")

    labels = {"workspace": "📁 Workspace files",
              "graph": "🕸️ Knowledge graph",
              "upload": "📤 Upload"}
    if len(available) == 1:
        choice = available[0]
    else:
        choice = st.radio("Scenario source:",
                          available, format_func=lambda s: labels.get(s, s),
                          horizontal=True, key=f"{key_prefix}_source")

    if choice == "workspace":
        selected = _load_from_workspace(key_prefix, allow_multiple, service, include_unlabelled)
    elif choice == "graph":
        selected = _load_from_graph(client, key_prefix, allow_multiple, service, include_unlabelled)
    else:
        selected = _load_from_upload(key_prefix, allow_multiple)

    if selected and show_preview:
        with st.expander(f"👁️ Preview ({len(selected)} scenario(s))", expanded=False):
            for item in selected:
                st.caption(f"**{item['name']}** · {item['source']}")
                st.code(item["content"][:2000], language="turtle")

    return selected
