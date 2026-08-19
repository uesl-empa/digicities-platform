# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Lazy triplestore provisioning for workspaces.

Backend-agnostic: works against both Apache Jena Fuseki (the v0.3 default) and
Ontotext GraphDB Free (opt-in via $TRIPLESTORE_BACKEND=graphdb). The triplestore
abstraction in backend/triplestore/ encapsulates the per-server REST differences
so this module stays focused on the workspace-aware logic.

When a user opens a registered workspace, this module makes sure the
triplestore has a dataset for it and that the workspace's TTLs are loaded into
the canonical named graphs. Idempotent — safe to call on every workspace open.

Layout inside each workspace's dataset:

    <http://ontology_dici_onto>   ← core ontology + workspace's ontology/extensions/*.ttl
    <http://classes_and_attributes> ← workspace's ingestion/output/*.ttl (component
                                      instances + attributes; this is also where the
                                      Replica Builder's "Upload to GraphDB" writes, so
                                      it persists instances to ingestion/output/ to
                                      survive the PUT/replace below)
    <http://system_description>   ← component-to-component links (replica-built; NOT
                                    written here, so re-provisioning never wipes them)
    <http://scenarios>            ← workspace's scenarios/*.ttl
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

from backend.triplestore import get_backend
from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SCENARIOS_GRAPH,
    COLLECTIONS_GRAPH,
)

from .context import WorkspaceContext


# Graph layout written by ensure_workspace_repo.
#
# Every authored section goes to its OWN named graph and nothing is written to
# the default graph. This keeps the dataset cleanly partitioned (replacing the
# ontology is a single PUT to <ontology_dici_onto> that leaves instances and
# links untouched) and keeps the platform portable: queries name the graphs
# they read via FROM clauses (see backend.graphdb.graphs.from_clause), so they
# return the same result on Fuseki, RDF4J, GraphDB or Oxigraph regardless of
# each store's default-graph/union semantics.
#
# The named graph IRIs are load-bearing and defined once in
# backend.graphdb.graphs:
#   <ontology_dici_onto>     core ontology + workspace extensions (schema)
#   <classes_and_attributes> component instances + their attributes
#   <system_description>     component-to-component links (replica-built; NOT
#                            written here so re-provisioning never wipes links)
#   <scenarios>              scenario graphs
#   <collections>            derived sets/statistics — CLEARED here on every
#                            reload (stale once the instance data changes)


def _core_ttl_path() -> Path:
    """Resolve the vendored core ontology TTL on the platform side."""
    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # backend/workspace/graphdb_provisioning.py → repo_root
    return repo_root / "services" / "graphdb" / "ontology" / "dici_onto_core.ttl"


# ---------------------------------------------------------------------------
# Thin convenience wrappers — kept exported for backwards compatibility, now
# delegate to the active triplestore backend.
# ---------------------------------------------------------------------------

def repository_exists(repo_id: str, base_url: Optional[str] = None) -> bool:
    return get_backend().dataset_exists(repo_id)


def create_repository(repo_id: str, label: str, base_url: Optional[str] = None) -> bool:
    return get_backend().create_dataset(repo_id, label=label)


def delete_repository(repo_id: str, base_url: Optional[str] = None) -> bool:
    return get_backend().delete_dataset(repo_id)


def clear_all_graphs(repo_id: str, base_url: Optional[str] = None) -> bool:
    """Empty a dataset completely: the default graph AND every named graph.

    ``CLEAR ALL`` is standard SPARQL 1.1 and behaves the same on both backends.
    The dataset itself survives, so the workspace stays open and usable; callers
    that want the core ontology back afterwards re-run ``ensure_workspace_repo``.
    """
    backend = get_backend()
    try:
        r = requests.post(
            backend.update_url(repo_id),
            data={"update": "CLEAR ALL"},
            auth=getattr(backend, "auth", None),
            timeout=120,
        )
        if r.status_code in (200, 204):
            return True
        print(f"[graphdb_provisioning] CLEAR ALL on {repo_id} returned HTTP {r.status_code}: {r.text[:200]}")
        return False
    except requests.RequestException as exc:
        print(f"[graphdb_provisioning] CLEAR ALL on {repo_id} failed: {exc}")
        return False


def upload_ttl_to_graph(
    repo_id: str,
    graph_iri: str,
    ttl_content: str,
    replace: bool = True,
    base_url: Optional[str] = None,
) -> bool:
    """PUT (replace) or POST (append) TTL into a named graph in the given dataset.

    Uses the active triplestore backend's auth credentials when present
    (Fuseki typically requires admin auth for writes; GraphDB Free is usually
    unauthenticated in local dev).
    """
    backend = get_backend()
    url = backend.graph_store_url(repo_id, graph_iri)
    method = "PUT" if replace else "POST"
    try:
        r = requests.request(
            method, url,
            data=ttl_content.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
            auth=getattr(backend, "auth", None),
            timeout=120,
        )
        if r.status_code not in (200, 201, 204):
            print(f"[graphdb_provisioning] upload to {repo_id}/{graph_iri} returned HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"[graphdb_provisioning] upload to {repo_id}/{graph_iri} failed: {exc}")
        return False


# Bookkeeping marker inside the collections graph: which authored-replica
# fingerprint the materialized collections were derived from. Plain URNs, not
# ontology terms — internal invalidation state, never domain vocabulary.
_COLLECTIONS_META_SUBJECT = "urn:digicities:collections"
_COLLECTIONS_META_PRED = "urn:digicities:replicaFingerprint"


def _replica_fingerprint(ctx, core_path) -> str:
    """Content hash of the AUTHORED replica sources (vendored core, workspace
    extensions, instance TTLs). Hashes the file bytes, not parsed graphs —
    blank-node labels make graph serializations unstable across runs."""
    import hashlib
    h = hashlib.sha256()
    try:
        h.update(Path(core_path).read_bytes())
    except Exception:
        pass
    for pattern in ("ontology/extensions/*.ttl", "ingestion/output/*.ttl"):
        try:
            for rel in sorted(ctx.storage.glob(pattern)):
                h.update(str(rel).encode("utf-8"))
                try:
                    h.update(ctx.storage.read_text(rel).encode("utf-8"))
                except Exception:
                    pass
        except Exception:
            pass
    return h.hexdigest()


def _collections_fingerprint(repo_id: str) -> Optional[str]:
    """The fingerprint the current collections graph was derived from, or None."""
    backend = get_backend()
    query = (f"SELECT ?v WHERE {{ GRAPH <{COLLECTIONS_GRAPH}> {{ "
             f"<{_COLLECTIONS_META_SUBJECT}> <{_COLLECTIONS_META_PRED}> ?v }} }}")
    try:
        r = requests.get(
            backend.query_url(repo_id), params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            auth=getattr(backend, "auth", None), timeout=30)
        if r.status_code != 200:
            return None
        bindings = r.json().get("results", {}).get("bindings", [])
        return bindings[0]["v"]["value"] if bindings else None
    except Exception:
        return None


def _stamp_collections_fingerprint(repo_id: str, fingerprint: str) -> None:
    backend = get_backend()
    update = (f"INSERT DATA {{ GRAPH <{COLLECTIONS_GRAPH}> {{ "
              f'<{_COLLECTIONS_META_SUBJECT}> <{_COLLECTIONS_META_PRED}> '
              f'"{fingerprint}" }} }}')
    try:
        requests.post(backend.update_url(repo_id), data={"update": update},
                      auth=getattr(backend, "auth", None), timeout=30)
    except requests.RequestException as exc:
        print(f"[graphdb_provisioning] fingerprint stamp on {repo_id} failed: {exc}")


def clear_graph(repo_id: str, graph_iri: str, base_url: Optional[str] = None) -> bool:
    """Empty one named graph with ``CLEAR SILENT GRAPH`` (no-op if absent)."""
    backend = get_backend()
    try:
        r = requests.post(
            backend.update_url(repo_id),
            data={"update": f"CLEAR SILENT GRAPH <{graph_iri}>"},
            auth=getattr(backend, "auth", None),
            timeout=60,
        )
        if r.status_code in (200, 204):
            return True
        print(f"[graphdb_provisioning] CLEAR GRAPH <{graph_iri}> on {repo_id} "
              f"returned HTTP {r.status_code}: {r.text[:200]}")
        return False
    except requests.RequestException as exc:
        print(f"[graphdb_provisioning] CLEAR GRAPH <{graph_iri}> on {repo_id} failed: {exc}")
        return False


def clear_default_graph(repo_id: str, base_url: Optional[str] = None) -> bool:
    """Empty the dataset's default graph with a SPARQL ``CLEAR DEFAULT`` update.

    Backend-agnostic and safe: ``CLEAR DEFAULT`` removes only the default
    (unnamed) graph, leaving every named graph intact. (A Graph-Store PUT to the
    default endpoint is NOT safe here — on GraphDB the default endpoint is
    ``/statements`` with no context, where a PUT replaces the whole repository.)
    """
    backend = get_backend()
    url = backend.update_url(repo_id)
    try:
        r = requests.post(
            url,
            data={"update": "CLEAR DEFAULT"},
            auth=getattr(backend, "auth", None),
            timeout=60,
        )
        if r.status_code in (200, 204):
            return True
        print(f"[graphdb_provisioning] CLEAR DEFAULT on {repo_id} returned HTTP {r.status_code}: {r.text[:200]}")
        return False
    except requests.RequestException as exc:
        print(f"[graphdb_provisioning] CLEAR DEFAULT on {repo_id} failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Per-workspace provisioning
# ---------------------------------------------------------------------------

def ensure_workspace_repo(ctx: WorkspaceContext, base_url: Optional[str] = None) -> bool:
    """Make sure the triplestore has a dataset for this workspace and that its
    canonical TTLs are loaded. Returns True if the dataset is usable after
    the call.

    Idempotent: when the dataset already exists, re-uploads the workspace's
    current ontology extensions / instance data / scenarios so any file edits
    show up in SPARQL queries without manual intervention.
    """
    repo_id = ctx.graphdb_repository
    if not repo_id:
        return False

    backend = get_backend()
    if not backend.dataset_exists(repo_id):
        if not backend.create_dataset(repo_id, label=f"Workspace: {ctx.name}"):
            return False

    # Build each authored section (schema / instances / scenarios) as its own
    # in-memory rdflib graph, materialize the RDFS-Plus closure, and PUT each to
    # its own named graph. Materializing at write time means application queries
    # can rely on inferred triples (subClassOf*/subPropertyOf*/inverseOf/sameAs/
    # ...) being physically present regardless of whether the active backend
    # materializes inference itself.

    import rdflib
    from .inference import materialize

    def _parse_glob(target: rdflib.Graph, pattern: str, kind: str) -> None:
        try:
            for rel in ctx.storage.glob(pattern):
                try:
                    target.parse(data=ctx.storage.read_text(rel), format="turtle")
                except Exception as exc:
                    print(f"[graphdb_provisioning] {kind} {rel} load skipped: {exc}")
        except Exception as exc:
            print(f"[graphdb_provisioning] {kind} listing failed: {exc}")

    # --- Build each authored section as its own graph and write it to its own
    #     named graph. Nothing is written to the default graph: readers name the
    #     graphs they need via FROM clauses, so transitivity is handled by SPARQL
    #     property paths (subClassOf*/subPropertyOf*) at query time — the pattern
    #     the Replica/Scenario Builders already use against these named graphs. ---

    # Schema: core ontology + workspace extensions, authored into <ontology_dici_onto>.
    schema_raw = rdflib.Graph()
    core_path = _core_ttl_path()
    if core_path.exists():
        try:
            schema_raw.parse(source=str(core_path), format="turtle")
        except Exception as exc:
            print(f"[graphdb_provisioning] core ontology load skipped: {exc}")
    _parse_glob(schema_raw, "ontology/extensions/*.ttl", "extension")

    # Instances: component data, authored into <classes_and_attributes>.
    instances_raw = rdflib.Graph()
    _parse_glob(instances_raw, "ingestion/output/*.ttl", "instance")

    # Scenarios → <scenarios> (kept as authored; no module reads them by name yet).
    scenarios = rdflib.Graph()
    _parse_glob(scenarios, "scenarios/*.ttl", "scenario")

    # --- Materialize the RDFS-Plus closure and split it across the two graphs so
    #     each is self-sufficient AND inferred *instance* triples (e.g.
    #     `inst a dici_onto:Component`, derived from `inst a WindTurbine` +
    #     `WindTurbine rdfs:subClassOf Component`) are physically present — the
    #     behaviour the old union+inference default graph provided, now without
    #     touching the default graph.
    #
    #     schema graph    = closure(schema)                 — the class/property hierarchy
    #     instances graph = closure(schema + instances) − closure(schema)
    #                       — instance triples + everything inferred from the
    #                         merge, minus the schema (so the schema isn't
    #                         duplicated and stays independently replaceable). ---
    schema = rdflib.Graph()
    schema += schema_raw
    try:
        added = materialize(schema, profile="rdfs-plus")
        print(f"[graphdb_provisioning] {ctx.id}: schema closure +{added} inferred = {len(schema)} total")
    except Exception as exc:
        print(f"[graphdb_provisioning] schema inference skipped: {exc}")

    merged = rdflib.Graph()
    merged += schema_raw
    merged += instances_raw
    try:
        added = materialize(merged, profile="rdfs-plus")
        print(f"[graphdb_provisioning] {ctx.id}: merged closure +{added} inferred = {len(merged)} total")
    except Exception as exc:
        print(f"[graphdb_provisioning] merged inference skipped: {exc}")

    # Instance graph = merged closure minus the schema closure (rdflib set diff).
    instances = merged - schema

    # Keep the default graph empty. Earlier (pre-named-graph) provisioning runs
    # dumped the full merged graph into the default graph; clear it so no reader
    # can pick up stale data and the dataset stays cleanly partitioned across
    # named graphs. CLEAR DEFAULT touches only the default graph, never the
    # named ones (so replica links in <system_description> are safe).
    if clear_default_graph(repo_id):
        print(f"[graphdb_provisioning] {ctx.id}: cleared default graph")
    else:
        print(f"[graphdb_provisioning] {ctx.id}: clearing default graph failed (non-fatal)")

    # --- Write each section to its named graph (PUT/replace, idempotent). The
    #     ontology write is fatal (queries are useless without the schema); the
    #     instance/scenario writes are best-effort. <system_description> is left
    #     alone here so re-provisioning on workspace open never wipes the links
    #     the Replica Builder writes there. ---
    try:
        if not upload_ttl_to_graph(repo_id, ONTOLOGY_GRAPH, schema.serialize(format="turtle"), replace=True):
            return False
        print(f"[graphdb_provisioning] {ctx.id}: wrote {len(schema)} triples to <{ONTOLOGY_GRAPH}>")
    except Exception as exc:
        print(f"[graphdb_provisioning] upload of schema graph failed: {exc}")
        return False

    for graph_iri, graph in (
        (CLASSES_AND_ATTRIBUTES_GRAPH, instances),
        (SCENARIOS_GRAPH, scenarios),
    ):
        try:
            if not upload_ttl_to_graph(repo_id, graph_iri, graph.serialize(format="turtle"), replace=True):
                print(f"[graphdb_provisioning] {ctx.id}: named-graph write to <{graph_iri}> failed (non-fatal)")
            else:
                print(f"[graphdb_provisioning] {ctx.id}: wrote {len(graph)} triples to <{graph_iri}>")
        except Exception as exc:
            print(f"[graphdb_provisioning] {ctx.id}: named-graph write to <{graph_iri}> raised (non-fatal): {exc}")

    # Collections are DERIVED from the authored replica — but a plain
    # workspace reopen re-uploads IDENTICAL data, and collections must survive
    # it (this ensure runs on every open; wiping unconditionally would erase
    # them the moment anyone opens the workspace). So: fingerprint the
    # authored sources and clear only when the content actually changed.
    # (<system_description> links are UI-written, not file-derived, so they
    # are outside the fingerprint — a collection stale by links alone is
    # recomputed from the Collections view.)
    fingerprint = _replica_fingerprint(ctx, core_path)
    previous = _collections_fingerprint(repo_id)
    if previous == fingerprint:
        print(f"[graphdb_provisioning] {ctx.id}: replica unchanged — "
              f"derived <{COLLECTIONS_GRAPH}> preserved")
    else:
        if clear_graph(repo_id, COLLECTIONS_GRAPH):
            print(f"[graphdb_provisioning] {ctx.id}: cleared derived "
                  f"<{COLLECTIONS_GRAPH}> (authored replica changed)")
        _stamp_collections_fingerprint(repo_id, fingerprint)

    # Opening/provisioning IS working on the workspace — record it so the
    # landing page's last-updated stamp reflects graph-only sessions too.
    from .deletion import touch_workspace_activity
    touch_workspace_activity(ctx.storage)

    return True
