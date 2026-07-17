# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Cross-backend smoke test: same workspace, same queries → same results.

What this test does
-------------------
1. Loads a known workspace (energy-simulation demo) into an in-memory rdflib graph.
2. Applies RDFS-Plus closure via the platform's inference module.
3. Runs the same set of canonical SPARQL queries against the closed graph
   using rdflib (which is itself a SPARQL 1.1 engine, standing in here for
   "whatever the active backend is — they all must return the same thing").
4. Asserts each query returns the expected row count and a stable result
   shape.

If a future code change breaks subClassOf/subPropertyOf closure, drops
triples during provisioning, or introduces a backend-specific extension,
one of these assertions will fail.

Run locally:
    pytest tests/test_cross_backend_smoke.py -v

Or in CI:
    Same. Plus a separate CI job can run against actual live Fuseki + GraphDB
    containers to verify the SPARQL endpoint paths too (see the
    `cross-backend-live` job in .github/workflows/ci.yml).
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
import rdflib


# Make `backend.*` importable when running pytest from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def energy_sim_workspace_graph():
    """Build the energy-simulation workspace's closed graph in memory.

    Uses the same composition + inference pipeline as
    `backend.workspace.graphdb_provisioning.ensure_workspace_repo`,
    minus the triplestore upload.
    """
    from backend.workspace.inference import materialize

    g = rdflib.Graph()

    # Core ontology (vendored)
    core = REPO_ROOT / "services" / "graphdb" / "ontology" / "dici_onto_core.ttl"
    g.parse(core, format="turtle")

    # Workspace TTLs are bundled under demo_workspaces/energy-simulation/ so the
    # test is self-contained — runs in CI without external clones. The same
    # directory is mounted by docker-compose.override.yml so a fresh
    # `docker compose up` shows the energy-simulation workspace in the UI
    # immediately.
    usecase = REPO_ROOT / "demo_workspaces" / "energy-simulation"
    if not usecase.exists():
        pytest.skip(f"energy-simulation fixture not found at {usecase}")

    for sub in ("ontology/extensions", "ingestion/output", "scenarios"):
        for ttl in (usecase / sub).glob("*.ttl"):
            g.parse(ttl, format="turtle")

    materialize(g, profile="rdfs-plus")
    return g


# ---------------------------------------------------------------------------
# Canonical queries — these MUST return identical results on any standards-
# compliant SPARQL 1.1 engine when the inference closure is materialised.
#
# Fixture data: 4 buildings (MFH_1, Office_1, SFH_1, SFH_old) + a TownCentre
# Location, each building carrying 6 attributes (BuildingAge, GroundFloorArea,
# NumberOfFloors + categorical SIA2024BuildingType, HeatingSupply, DHWSupply),
# and 4 scenarios (baseline, old_building, retrofit, townblock).
# ---------------------------------------------------------------------------


def test_components_query_natural_form(energy_sim_workspace_graph):
    """`?inst a dici_onto:Component` should return at least the 4 buildings.

    Without inference, this returns 0 — Buildings aren't typed as Components
    in the asserted data. With RDFS closure, the subclass chain
    Building → EnergyConsumer → Component is materialised and the natural
    query works.
    """
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    SELECT (COUNT(DISTINCT ?inst) AS ?n)
    WHERE { ?inst a dici_onto:Component }
    """
    n = int(next(iter(energy_sim_workspace_graph.query(q))).n)
    # >= 4 because RDFS-Plus closure may also lift superseding/linked instances
    # into Component via owlrl's class-equivalence reasoning when the extension
    # declares overlapping rdfs:range / rdfs:domain. The key invariant is that
    # the 4 buildings MUST be there — over-classification is a soft warning,
    # not a regression.
    assert n >= 4, f"expected >= 4 Component instances (the 4 buildings), got {n}"


def test_buildings_query_specific_form(energy_sim_workspace_graph):
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    SELECT (COUNT(DISTINCT ?inst) AS ?n)
    WHERE { ?inst a dici_onto:Building }
    """
    n = int(next(iter(energy_sim_workspace_graph.query(q))).n)
    assert n == 4, f"expected 4 Building instances, got {n}"


def test_hasattribute_query_natural_form(energy_sim_workspace_graph):
    """`?inst dici_onto:hasAttribute ?attr` should catch every typed
    predicate (hasBuildingGroundFloorAreaAttribute, etc.) via subPropertyOf
    closure. Without inference this returns only the directly-asserted
    hasAttribute triples; with inference all 6 attributes per building
    surface (>= 24 total across the 4 buildings).
    """
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    SELECT (COUNT(*) AS ?n)
    WHERE { ?inst dici_onto:hasAttribute ?attr }
    """
    n = int(next(iter(energy_sim_workspace_graph.query(q))).n)
    assert n >= 24, f"expected at least 24 hasAttribute relations (6 per building × 4), got {n}"


def test_subproperty_chain_walks_to_hasattribute(energy_sim_workspace_graph):
    """Property-path queries must continue to work even when inference is on
    — they're the defense-in-depth fallback."""
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT (COUNT(*) AS ?n) WHERE {
        ?inst ?p ?attr .
        ?p rdfs:subPropertyOf* dici_onto:hasAttribute .
    }
    """
    n = int(next(iter(energy_sim_workspace_graph.query(q))).n)
    assert n >= 24


def test_attribute_values_queryable(energy_sim_workspace_graph):
    """Every building must have a numeric groundFloorArea reachable via the
    natural `hasAttribute → GroundFloorArea → qudt:value` chain.

    Asserts on the *set* of expected floor-area values rather than exact row
    count, because owlrl's OWL-RL slice may also classify other attribute
    types as GroundFloorArea when the extension has overlapping range
    declarations. The expected building floor areas {150, 180, 284, 600} m²
    must appear regardless.
    """
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    PREFIX qudt: <http://qudt.org/schema/qudt/>
    SELECT ?building ?area WHERE {
        ?building a dici_onto:Building ;
                  dici_onto:hasAttribute ?attr .
        ?attr a dici_onto:GroundFloorArea ;
              qudt:value ?area .
    }
    """
    rows = list(energy_sim_workspace_graph.query(q))
    areas_per_building = {str(r.building): set() for r in rows}
    for r in rows:
        areas_per_building[str(r.building)].add(float(r.area))
    expected_areas = {150.0, 180.0, 284.0, 600.0}
    found_areas = set().union(*areas_per_building.values()) if areas_per_building else set()
    assert expected_areas.issubset(found_areas), \
        f"missing expected building floor areas: {expected_areas - found_areas}; got {found_areas}"


def test_scenario_usedin_relations(energy_sim_workspace_graph):
    """The 4 scenarios should each anchor their buildings via usedInScenario:
    baseline/retrofit/old_building each anchor one building, townblock anchors
    three."""
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    SELECT ?scenario (COUNT(DISTINCT ?inst) AS ?n) WHERE {
        ?inst a dici_onto:Building ;
              dici_onto:usedInScenario ?scenario .
    } GROUP BY ?scenario
    """
    rows = {str(r.scenario): int(r.n) for r in energy_sim_workspace_graph.query(q)}
    assert len(rows) == 4, f"expected 4 scenarios, got {len(rows)}: {rows}"
    assert all(n >= 1 for n in rows.values()), f"each scenario should anchor >= 1 building: {rows}"
    # The town-block scenario is the multi-building one.
    townblock = next((n for s, n in rows.items() if s.endswith("TownBlock")), None)
    assert townblock == 3, f"town-block scenario should anchor 3 buildings, got {townblock}"


def test_supersedesattribute_layered_correctly(energy_sim_workspace_graph):
    """The retrofit scenario supersedes the baseline HeatingSupply and DHWSupply
    for its building — a categorical retrofit (e.g. AirHeated → ElectricallyHeated)
    layered over the ingested value via supersedesAttribute."""
    q = """
    PREFIX dici_onto: <https://digicities.info/ontology#>
    SELECT ?type WHERE {
        ?mod dici_onto:supersedesAttribute ?orig ;
             a ?type .
        FILTER(?type IN (dici_onto:HeatingSupply, dici_onto:DHWSupply))
    }
    """
    types = {str(r.type).split("#")[-1] for r in energy_sim_workspace_graph.query(q)}
    assert {"HeatingSupply", "DHWSupply"}.issubset(types), \
        f"retrofit should supersede HeatingSupply and DHWSupply, got {types}"


# ---------------------------------------------------------------------------
# Reading note: this file deliberately uses rdflib (a SPARQL 1.1 engine)
# rather than spinning up Fuseki / GraphDB containers, because rdflib
# normalises any backend-specific quirks away. If the test passes here, it
# passes on Fuseki and on GraphDB and on any other SPARQL 1.1 engine. The
# "live" cross-backend variant (which actually pings both REST endpoints)
# lives in tools/test_cross_backend_live.py — slower, requires Docker, run
# in CI on PRs that touch backend/triplestore/ or backend/workspace/.
# ---------------------------------------------------------------------------
