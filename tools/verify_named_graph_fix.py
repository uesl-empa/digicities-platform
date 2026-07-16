# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Verify the named-graph read/write fix end to end against the live triplestore.

Run inside the streamlit container:
    docker cp tools/verify_named_graph_fix.py digicities-streamlit:/tmp/
    MSYS_NO_PATHCONV=1 docker exec digicities-streamlit python //tmp/verify_named_graph_fix.py
"""
import sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/apps/streamlit")

from backend.workspace.registry import load_registry
from backend.workspace.graphdb_provisioning import ensure_workspace_repo
from backend.graphdb.graphs import (
    ONTOLOGY_GRAPH,
    CLASSES_AND_ATTRIBUTES_GRAPH,
    from_clause,
)
from components.graphdb import GraphDBClient


def pick_workspace():
    reg = load_registry()
    print(f"workspaces discovered: {reg.ids()}")
    for ctx in reg:
        try:
            ttls = list(ctx.storage.glob("ingestion/output/*.ttl"))
        except Exception as exc:
            print(f"  {ctx.id}: glob failed: {exc}")
            ttls = []
        if ttls:
            print(f"  -> using '{ctx.id}' ({len(ttls)} instance TTL files)")
            return ctx
    return None


def main():
    ctx = pick_workspace()
    if ctx is None:
        print("NO workspace with ingestion/output TTLs found; cannot verify.")
        return

    print(f"\n=== re-provisioning '{ctx.id}' with the new named-graph layout ===")
    ok = ensure_workspace_repo(ctx)
    print(f"ensure_workspace_repo -> {ok}")

    repo = ctx.graphdb_repository
    client = GraphDBClient(token="local", selected_repo=repo)

    # 1) Per-graph triple counts (proves data is partitioned into named graphs).
    print("\n=== named-graph triple counts ===")
    g_counts = client.sparql_api_query(
        "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g",
        out_format="df",
    )
    print(g_counts if g_counts is not None else "<query failed>")

    # 2) Default-graph count (clause-less). On Fuseki this reads ONLY the default
    #    graph, which we intentionally leave empty -> should be 0.
    print("\n=== default-graph triple count (clause-less; expect 0 on Fuseki) ===")
    d = client.sparql_api_query(
        "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }", out_format="df"
    )
    print(d if d is not None else "<query failed>")

    # 3) Bug-then-fix: component discovery query, clause-less vs FROM named graphs.
    body = """
      ?class rdfs:subClassOf* dici_onto:Component .
      OPTIONAL { ?class rdfs:label ?label }
    """
    prefixes = (
        "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    )
    clause_less = f"{prefixes}SELECT DISTINCT ?class ?label WHERE {{{body}}}"
    with_from = (
        f"{prefixes}SELECT DISTINCT ?class ?label\n"
        f"{from_clause(ONTOLOGY_GRAPH, CLASSES_AND_ATTRIBUTES_GRAPH)}WHERE {{{body}}}"
    )

    cl = client.sparql_api_query(clause_less, out_format="df")
    wf = client.sparql_api_query(with_from, out_format="df")
    n_cl = 0 if cl is None or cl.empty else len(cl)
    n_wf = 0 if wf is None or wf.empty else len(wf)
    print("\n=== component discovery query ===")
    print(f"clause-less (old behaviour) -> {n_cl} components")
    print(f"FROM named graphs (the fix) -> {n_wf} components")

    # 4) Exercise the real reader functions through the app's code path.
    print("\n=== real reader functions ===")
    from components.component_explorer import get_component_types_with_instances
    from components.service_requirements_builder import query_graphdb_components

    ce = get_component_types_with_instances(client)
    print(f"component_explorer.get_component_types_with_instances -> "
          f"{0 if ce is None or ce.empty else len(ce)} rows")

    comps, attrs = query_graphdb_components(client)
    print(f"service_requirements_builder.query_graphdb_components -> "
          f"{len(comps)} components, {len(attrs)} attributes")

    print("\n=== verdict ===")
    if n_wf > 0 and n_cl == 0:
        print("PASS: named-graph FROM queries return data; default graph is empty "
              "(bug reproduced AND fixed).")
    elif n_wf > 0 and n_cl > 0:
        print("PARTIAL: FROM queries work; clause-less also returned data "
              "(this backend unions named graphs into the default).")
    else:
        print("FAIL: FROM queries returned no components — investigate.")


if __name__ == "__main__":
    main()
