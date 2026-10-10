# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""A scenario inherits the overrides of the scenarios it is based on.

2030 -> 2040 -> 2050: each year is based on the one before (``basedOn``) and
overrides some values. Materialising a year gives that year's overrides plus
every inherited one it does not replace (the nearest scenario wins), whether
the later year supersedes the replica attribute or the earlier year's
override. A cycle or two parents is an error, a missing parent is reported.
Runs against the REAL vendored core.
"""
from __future__ import annotations

import pytest
from rdflib import Graph, URIRef

from backend.graphdb.queries.scenarios import (
    ScenarioMaterializationError, materialize_scenario_graphs, scenario_lineage,
)
from backend.ontology_kinds import core_graph

D = "https://digicities.info/ontology#"
QUDT_VALUE = URIRef("http://qudt.org/schema/qudt/value")
P = "https://digicities.info/proj/ws"
WT = f"{P}/WindTurbine/WT1"
POWER, HUB = f"{WT}/RatedPower", f"{WT}/HubHeight"
POWER_P, HUB_P = (URIRef(f"{D}hasWindTurbineRatedPowerAttribute"),
                  URIRef(f"{D}hasWindTurbineHubHeightAttribute"))
USED = URIRef(f"{D}usedInScenario")

ONTOLOGY = f"""
@prefix dici_onto: <{D}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:WindTurbine rdfs:subClassOf dici_onto:Component .
dici_onto:RatedPower rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:PhysicalAttribute .
dici_onto:HubHeight rdfs:subClassOf dici_onto:ComponentAttribute, dici_onto:PhysicalAttribute .
dici_onto:hasWindTurbineRatedPowerAttribute rdfs:subPropertyOf dici_onto:hasAttribute .
dici_onto:hasWindTurbineHubHeightAttribute rdfs:subPropertyOf dici_onto:hasAttribute .
"""

REPLICA = f"""
@prefix dici_onto: <{D}> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{WT}> a dici_onto:WindTurbine ;
    dici_onto:hasWindTurbineRatedPowerAttribute <{POWER}> ;
    dici_onto:hasWindTurbineHubHeightAttribute <{HUB}> .
<{POWER}> a dici_onto:RatedPower ; qudt:value 2.0 .
<{HUB}> a dici_onto:HubHeight ; qudt:value 80.0 .
"""

PREFIXES = f"""
@prefix dici_onto: <{D}> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
"""


def _year(year: int, parent, overrides: dict, parent_prop: str = "basedOn") -> str:
    """A thin scenario for ``year``: anchors the turbine, overrides
    ``{superseded IRI: value}``."""
    scn = f"{P}/S{year}"
    ttl = f"<{scn}> a dici_onto:Scenario"
    ttl += f" ; dici_onto:{parent_prop} <{parent}> .\n" if parent else " .\n"
    ttl += f"<{WT}> dici_onto:usedInScenario <{scn}> .\n"
    for i, (old, value) in enumerate(overrides.items()):
        ttl += (f"<{scn}/ov{i}> a dici_onto:PhysicalAttribute ; qudt:value {value} ;\n"
                f"    dici_onto:supersedesAttribute <{old}> ;\n"
                f"    dici_onto:usedInScenario <{scn}> .\n")
    return ttl


def _chain() -> Graph:
    g = Graph()
    g.parse(data=PREFIXES + _year(2025, None, {}), format="turtle")
    g.parse(data=PREFIXES + _year(2030, f"{P}/S2025", {POWER: 3.0, HUB: 100.0}), format="turtle")
    g.parse(data=PREFIXES + _year(2040, f"{P}/S2030", {POWER: 4.0}), format="turtle")
    # 2050 supersedes 2040's override node, not the replica attribute.
    g.parse(data=PREFIXES + _year(2050, f"{P}/S2040", {f"{P}/S2040/ov0": 5.0}), format="turtle")
    return g


def _values(scn: Graph, year: int, warnings=None):
    ttl = materialize_scenario_graphs(
        scn, Graph().parse(data=REPLICA, format="turtle"), f"{P}/S{year}",
        ontology_graph=Graph().parse(data=ONTOLOGY, format="turtle"), warnings=warnings)
    out = Graph().parse(data=ttl, format="turtle")

    def value(pred):
        return {float(v) for a in out.objects(URIRef(WT), pred) for v in out.objects(a, QUDT_VALUE)}
    return value(POWER_P), value(HUB_P), out


@pytest.mark.parametrize("year, power, hub", [
    (2025, 2.0, 80.0), (2030, 3.0, 100.0), (2040, 4.0, 100.0), (2050, 5.0, 100.0)])
def test_each_year_inherits_the_earlier_overrides_and_the_nearest_wins(year, power, hub):
    got_power, got_hub, _ = _values(_chain(), year)
    assert got_power == {power}
    assert got_hub == {hub}


def test_inherited_overrides_are_tagged_with_the_materialised_scenario_only():
    _, _, out = _values(_chain(), 2050)
    hub_node = next(out.objects(URIRef(WT), HUB_P))
    assert hub_node == URIRef(f"{P}/S2030/ov1")
    assert set(out.objects(hub_node, USED)) == {URIRef(f"{P}/S2050")}


def test_lineage_follows_based_on():
    schema = core_graph()
    assert scenario_lineage(_chain(), URIRef(f"{P}/S2050"), schema) == [
        URIRef(f"{P}/S{y}") for y in (2050, 2040, 2030, 2025)]


def test_the_deprecated_derived_from_alias_is_followed_too():
    g = _chain()
    g.parse(data=PREFIXES + _year(2060, f"{P}/S2050", {}, parent_prop="derivedFrom"),
            format="turtle")
    power, hub, _ = _values(g, 2060)
    assert (power, hub) == ({5.0}, {100.0})


def test_a_cycle_is_refused():
    g = Graph()
    g.parse(data=PREFIXES + _year(2030, f"{P}/S2040", {POWER: 3.0}), format="turtle")
    g.parse(data=PREFIXES + _year(2040, f"{P}/S2030", {POWER: 4.0}), format="turtle")
    with pytest.raises(ScenarioMaterializationError, match="cycle"):
        _values(g, 2040)


def test_two_parents_are_refused():
    g = _chain()
    g.parse(data=PREFIXES + f"<{P}/S2040> dici_onto:basedOn <{P}/S2025> .", format="turtle")
    with pytest.raises(ScenarioMaterializationError, match="based on 2 scenarios"):
        _values(g, 2050)


def test_a_missing_parent_is_reported_and_own_overrides_still_apply():
    g = Graph().parse(data=PREFIXES + _year(2040, f"{P}/S2030", {POWER: 4.0}), format="turtle")
    notes: list = []
    power, hub, _ = _values(g, 2040, warnings=notes)
    assert (power, hub) == ({4.0}, {80.0})
    assert len(notes) == 1 and f"{P}/S2030" in notes[0]


def test_a_scenario_file_inherits_from_the_workspace_scenario_files(tmp_path):
    """The REST convert path reads one scenario file; its parents come from the
    workspace's other scenario files."""
    from backend.api_submission.materialize import materialize_against_workspace
    from backend.workspace.storage import WorkspaceStorage

    storage = WorkspaceStorage.local(str(tmp_path))
    storage.write_text("ingestion/output/replica.ttl", REPLICA)
    storage.write_text("ontology/extensions/ext.ttl", PREFIXES + ONTOLOGY)
    for year, parent, ov in ((2030, None, {POWER: 3.0, HUB: 100.0}),
                             (2040, f"{P}/S2030", {POWER: 4.0})):
        storage.write_text(f"scenarios/s{year}.ttl", PREFIXES + _year(year, parent, ov))
    skipped: list = []
    merged = materialize_against_workspace(
        storage, storage.read_text("scenarios/s2040.ttl"), skipped=skipped)
    out = Graph().parse(data=merged, format="turtle")
    hub = {float(v) for a in out.objects(URIRef(WT), HUB_P) for v in out.objects(a, QUDT_VALUE)}
    power = {float(v) for a in out.objects(URIRef(WT), POWER_P) for v in out.objects(a, QUDT_VALUE)}
    assert (power, hub) == ({4.0}, {100.0})
    assert skipped == []
