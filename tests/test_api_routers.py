# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""HTTP contract tests for the REST routers the React frontend drives.

These pin routing, validation, on-disk side effects, and error mapping — the
seam the frontend's hand-written client (src/api.ts) depends on. Heavy backend
logic has its own suites; graph-reading endpoints (palette, instances) and the
LLM-backed agent are exercised with stand-ins, because what must not regress
here is the HTTP contract, not the store.

Windows note: zip-slip is tested with a crafted entry name, no real extraction
outside tmp ever happens.
"""
from __future__ import annotations

import io
import json
import sys
import types
import zipfile

import pytest

fastapi = pytest.importorskip("fastapi")

import rdflib  # noqa: E402
import yaml  # noqa: E402


pytestmark = pytest.mark.api


class _Ctx:
    id = "testws"
    name = "Test Workspace"
    graphdb_repository = "testws"
    description = "router-test workspace"


@pytest.fixture()
def ws(tmp_path, monkeypatch, api_app):
    """A fake open workspace: ctx override + USECASES_DIR pointed at tmp."""
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx
    from backend.workspace import WorkspaceStorage

    root = tmp_path / _Ctx.id
    root.mkdir()
    # Real WorkspaceContexts always carry a storage; the stub gets one over
    # the same tmp root (workspace_info reads metadata through it).
    ctx = _Ctx()
    ctx.storage = WorkspaceStorage.local(str(root))
    api_app.dependency_overrides[get_ctx] = lambda: ctx
    return root


@pytest.fixture()
def client(api_client):
    return api_client


B = f"/api/workspaces/{_Ctx.id}"


# ── scenario ──────────────────────────────────────────────────────────────────
def test_scenario_build_saves_valid_ttl_and_lists_it(client, ws):
    spec = {
        "scenario_name": "My Scenario",
        "components": [
            {"uri": "https://digicities.info/proj/testws/Building/B1",
             "type": "Building", "label": "B1"},
            {"uri": "https://digicities.info/proj/testws/Location/L1"},
        ],
        "links": [{"source": "https://digicities.info/proj/testws/Location/L1",
                   "target": "https://digicities.info/proj/testws/Building/B1"}],
    }
    r = client.post(f"{B}/scenario/build", json=spec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == "My_Scenario.ttl"
    g = rdflib.Graph()
    g.parse(data=body["ttl"], format="turtle")  # must be valid Turtle
    assert len(g) > 0

    assert client.get(f"{B}/scenario/list").json() == ["My_Scenario.ttl"]
    got = client.get(f"{B}/scenario/ttl", params={"name": "My_Scenario.ttl"})
    assert got.status_code == 200
    assert got.json()["ttl"] == body["ttl"]


def test_scenario_build_full_draft_uses_full_emitter(client, ws):
    """A spec whose components carry attributes/nested_properties routes to the
    full backend emitter (issue #17): typed attribute nodes, High-specificity
    property names, a TimeSeries resource, and typed links come back."""
    wt = "https://digicities.info/proj/testws/WindTurbine/WT1"
    edp = "https://digicities.info/proj/testws/ElectricityDemandProfile/EDP1"
    ts = "https://digicities.info/proj/testws/ts/demand"
    spec = {
        "scenario_name": "Full Draft",
        "service_name": "golden_service",
        "ttl_specificity": "High",
        "required_attributes": {
            "WindTurbine": ["hubHeight"],
            "ElectricityDemandProfile": ["Power.hasHistoricTimeSeriesReference"],
        },
        "components": [
            {"uri": wt, "type": "WindTurbine", "label": "Turbine One",
             "source": "ttl_use_case",
             "attributes": {"hubHeight": {"value": 120, "unit": "m",
                                          "attribute_type": "PhysicalAttribute"}}},
            {"uri": edp, "type": "ElectricityDemandProfile", "label": "Demand One",
             "source": "data_products",
             "attributes": {"Power": {"value": "timeseries", "unit": "kW"}},
             "nested_properties": {"Power": {
                 "hasHistoricTimeSeriesReference": "resources/demand.csv",
                 "hasHistoricTimeSeries": ts,
                 "unit": "kW"}}},
        ],
        "links": [
            {"source": "scenario", "target": wt, "link_type": "scenario_automatic"},
            {"source": edp, "target": wt, "link_type": "feeds"},
        ],
    }
    r = client.post(f"{B}/scenario/build", json=spec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == "Full_Draft.ttl"

    g = rdflib.Graph()
    g.parse(data=body["ttl"], format="turtle")
    dici = rdflib.Namespace("https://digicities.info/ontology#")
    qudt = rdflib.Namespace("http://qudt.org/schema/qudt/")
    xsd = rdflib.namespace.XSD
    scenario = rdflib.URIRef("https://digicities.info/proj/testws/Full_Draft")

    # Full-emitter attribute node with the High-specificity property name.
    attr = rdflib.URIRef(f"{wt}/hubHeight")
    assert (rdflib.URIRef(wt), dici.hasWindTurbinehubHeightAttribute, attr) in g
    assert (attr, rdflib.RDF.type, dici.PhysicalAttribute) in g
    assert (attr, qudt.value, rdflib.Literal("120", datatype=xsd.decimal)) in g

    # Nested time-series promotion: DynamicAttribute + TimeSeries resource.
    power = rdflib.URIRef(f"{edp}/Power")
    assert (power, rdflib.RDF.type, dici.DynamicAttribute) in g
    assert (rdflib.URIRef(ts), rdflib.RDF.type, dici.TimeSeries) in g
    assert (rdflib.URIRef(ts), dici.storedAt,
            rdflib.Literal("resources/demand.csv", datatype=xsd.string)) in g

    # Scenario header and both link flavors (with the pinned typo predicate).
    assert (scenario, dici.builtForService, rdflib.Literal("golden_service")) in g
    link_targets = set(g.objects(None, dici.linksInputyEntityTo))
    assert link_targets == {rdflib.URIRef(wt)}
    link_types = {str(o) for o in g.objects(None, dici.linkType)}
    assert link_types == {"scenario_automatic", "feeds"}


def test_scenario_build_full_draft_requires_component_types(client, ws):
    """Full-emitter specs must type every component; the ValueError surfaces
    as a 400, not a 500."""
    r = client.post(f"{B}/scenario/build", json={
        "scenario_name": "Bad",
        "components": [{"uri": "https://x/WT1",
                        "attributes": {"a": {"value": 1}}}],
    })
    assert r.status_code == 400
    assert "type" in r.json()["detail"]


def test_scenario_build_requires_name_and_components(client, ws):
    r = client.post(f"{B}/scenario/build",
                    json={"scenario_name": " ", "components": [{"uri": "x"}]})
    assert r.status_code == 400
    r = client.post(f"{B}/scenario/build",
                    json={"scenario_name": "S", "components": []})
    assert r.status_code == 400


def test_scenario_ttl_404_for_unknown(client, ws):
    assert client.get(f"{B}/scenario/ttl", params={"name": "nope.ttl"}).status_code == 404


def test_scenario_draft_round_trip(client, ws):
    """Build a scenario, then load it back as an editable draft."""
    wt = "https://example.org/x/WindTurbine/WT1"
    r = client.post(f"{B}/scenario/build", json={
        "scenario_name": "Reload Me",
        "components": [{"uri": wt, "type": "WindTurbine", "label": "WT1"}],
        "links": [{"source": "scenario", "target": wt, "link_type": "scenario_automatic"}],
        "service_name": "golden_service",
    })
    assert r.status_code == 200
    r = client.get(f"{B}/scenario/draft", params={"name": "Reload_Me.ttl"})
    assert r.status_code == 200
    d = r.json()
    assert d["scenario_name"] == "Reload Me"
    assert d["service_name"] == "golden_service"
    assert d["components"] == [{"uri": wt, "type": "WindTurbine", "label": "WT1"}]
    assert d["links"] == [{"source": "scenario", "target": wt,
                           "link_type": "scenario_automatic",
                           "pattern": "CL.Scenario.WindTurbine"}]


def test_scenario_draft_404_for_unknown(client, ws):
    assert client.get(f"{B}/scenario/draft", params={"name": "nope.ttl"}).status_code == 404


def test_scenario_link_suggestions_degrade_without_graph(client, ws):
    """No reachable graph → empty suggestions, not a 500."""
    r = client.get(f"{B}/scenario/link-suggestions")
    assert r.status_code == 200
    assert r.json() == {"discovered": [], "matched": {}}


def test_scenario_materialized_merges_replica_values(client, ws):
    """The materialized export is the thin scenario + replica values applied —
    a self-contained full TTL derived on demand."""
    wt = "https://x/proj/testws/WindTurbine/W1"
    d = ws / "ingestion" / "output"
    d.mkdir(parents=True)
    (d / "replica.ttl").write_text(f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{wt}> a dici_onto:WindTurbine ;
    dici_onto:hasWindTurbineHubHeightAttribute <{wt}/HubHeight> .
<{wt}/HubHeight> a dici_onto:PhysicalAttribute ; qudt:value 85.0 .
""", encoding="utf-8")
    client.post(f"{B}/scenario/build", json={
        "scenario_name": "Mat", "components": [{"uri": wt, "type": "WindTurbine", "label": "W1"}],
        "links": [{"source": "scenario", "target": wt, "link_type": "scenario_automatic"}]})
    r = client.get(f"{B}/scenario/materialized", params={"name": "Mat.ttl"})
    assert r.status_code == 200
    got = r.json()
    assert got["materialized"] is True
    g = rdflib.Graph()
    g.parse(data=got["ttl"], format="turtle")
    qudt = rdflib.Namespace("http://qudt.org/schema/qudt/")
    values = [str(o) for o in g.objects(rdflib.URIRef(f"{wt}/HubHeight"), qudt.value)]
    assert values == ["85.0"]
    assert client.get(f"{B}/scenario/materialized",
                      params={"name": "nope.ttl"}).status_code == 404


def test_scenario_delete_removes_file_even_without_graph(client, ws):
    wt = "https://example.org/x/WindTurbine/WT9"
    client.post(f"{B}/scenario/build", json={
        "scenario_name": "Doomed", "components": [{"uri": wt, "type": "WindTurbine"}]})
    assert client.get(f"{B}/scenario/list").json() == ["Doomed.ttl"]
    r = client.delete(f"{B}/scenario", params={"name": "Doomed.ttl"})
    assert r.status_code == 200
    got = r.json()
    assert got["deleted"] == "Doomed.ttl" and got["graph_cleaned"] is False
    assert client.get(f"{B}/scenario/list").json() == []
    assert client.delete(f"{B}/scenario", params={"name": "Doomed.ttl"}).status_code == 404


def test_scenario_push_404_for_unknown(client, ws):
    assert client.post(f"{B}/scenario/push", json={"name": "nope.ttl"}).status_code == 404


def test_scenario_build_thin_substitutes_scenario_pseudo_source(client, ws):
    """Auto scenario→component links use the pseudo-source 'scenario'; the
    thin build must swap in the scenario IRI, never emit <scenario>."""
    wt = "https://example.org/x/WindTurbine/WT1"
    r = client.post(f"{B}/scenario/build", json={
        "scenario_name": "Thin Auto",
        "components": [{"uri": wt, "type": "WindTurbine", "label": "WT1"}],
        "links": [{"source": "scenario", "target": wt, "link_type": "scenario_automatic"}],
    })
    assert r.status_code == 200
    ttl = r.json()["ttl"]
    assert "<scenario>" not in ttl
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    dici = rdflib.Namespace("https://digicities.info/ontology#")
    sources = list(g.objects(predicate=dici.hasInputEntity))
    assert sources and str(sources[0]).endswith("/Thin_Auto")


_SERVICE_YAML = """\
service_name: demo_sim
connection: {transport: http, url: http://x, method: POST}
scenario_data:
  uri: Scenario.URI
  location:
    link: CL.Scenario.Location
    template:
      uri: Location.URI
      buildings:
        link: CL.Location.Building
        template:
          uri: Building.URI
          GroundFloorArea: Building.GroundFloorArea
"""


def _write_service(ws):
    d = ws / "services"
    d.mkdir(exist_ok=True)
    (d / "demo_sim.yaml").write_text(_SERVICE_YAML, encoding="utf-8")


def test_scenario_requirements_parses_service_template(client, ws):
    _write_service(ws)
    # Resolvable by file name, stem, or service_name.
    for key in ("demo_sim.yaml", "demo_sim"):
        r = client.get(f"{B}/scenario/requirements", params={"service": key})
        assert r.status_code == 200
    got = r.json()
    assert got["service_name"] == "demo_sim"
    assert got["file"] == "demo_sim.yaml"
    assert got["component_links"] == ["CL.Location.Building", "CL.Scenario.Location"]
    assert set(got["required_component_types"]) >= {"Location", "Building"}
    assert set(got["required_attributes"]["Building"]) == {"URI", "GroundFloorArea"}


def test_scenario_requirements_404_for_unknown_service(client, ws):
    assert client.get(f"{B}/scenario/requirements",
                      params={"service": "nope"}).status_code == 404


def test_scenario_validate_flags_missing_and_previews_exclusion(client, ws):
    """The validate endpoint mirrors the emitter's completeness gate: a
    component missing a required attribute is excluded, and links touching
    it are dropped with it."""
    _write_service(ws)
    b1 = "https://x/Building/B1"
    b2 = "https://x/Building/B2"
    loc = "https://x/Location/L1"
    r = client.post(f"{B}/scenario/validate", json={
        "service": "demo_sim",
        "components": [
            {"uri": b1, "type": "Building", "label": "B1",
             "attributes": {"GroundFloorArea": {"value": 120.0}}},
            {"uri": b2, "type": "Building", "label": "B2",
             "attributes": {"SomethingElse": {"value": 1}}},
            {"uri": loc, "type": "Location", "label": "L1",
             "attributes": {"WeatherEPW": {"value": "demo.epw"}}},
        ],
        "links": [
            {"source": "scenario", "target": loc, "link_type": "scenario_automatic"},
            {"source": loc, "target": b1},
            {"source": loc, "target": b2},
        ],
    })
    assert r.status_code == 200
    got = r.json()
    by_uri = {c["uri"]: c for c in got["components"]}
    # URI/label are synthesized like the Streamlit builder does on add.
    assert by_uri[b1]["status"] == "compliant" and by_uri[b1]["included"]
    assert by_uri[b2]["status"] == "partial" and not by_uri[b2]["included"]
    assert by_uri[b2]["missing"] == ["GroundFloorArea"]
    assert by_uri[loc]["status"] == "compliant"
    assert got["summary"] == {"total": 3, "compliant": 2, "partial": 1,
                              "missing_all": 0, "excluded": 1}
    # The link into the excluded B2 is dropped; scenario pseudo-link survives.
    assert got["links"] == {"total": 3, "kept": 2, "dropped": 1}


def test_scenario_validate_diagnoses_template_mismatch(client, ws):
    """An attribute missing on EVERY component of a type is reported as a
    template/replica mismatch, not left as per-instance noise."""
    r = client.post(f"{B}/scenario/validate", json={
        "required_attributes": {"RoadSegment": ["Capacity", "HourlyVehicleCount"]},
        "components": [
            {"uri": "https://x/RS/R1", "type": "RoadSegment", "label": "R1",
             "attributes": {"Capacity": {"value": 100}}},
            {"uri": "https://x/RS/R2", "type": "RoadSegment", "label": "R2",
             "attributes": {"Capacity": {"value": 200}}},
        ],
    })
    assert r.status_code == 200
    got = r.json()
    # Capacity present on both -> no diagnostic; HourlyVehicleCount on none -> flagged.
    assert len(got["diagnostics"]) == 1
    d = got["diagnostics"][0]
    assert d["type"] == "RoadSegment" and d["attribute"] == "HourlyVehicleCount"
    assert "mismatch" in d["note"]


def test_scenario_validate_accepts_inline_requirements(client, ws):
    """No service file needed — the caller may pass required_attributes
    directly (a type with no requirements is compliant by definition)."""
    r = client.post(f"{B}/scenario/validate", json={
        "required_attributes": {"WindTurbine": ["HubHeight"]},
        "components": [
            {"uri": "https://x/WT1", "type": "WindTurbine", "label": "WT1"},
            {"uri": "https://x/EDP1", "type": "EnergyDataPoint", "label": "E1"},
        ],
    })
    assert r.status_code == 200
    got = r.json()
    by_uri = {c["uri"]: c for c in got["components"]}
    assert by_uri["https://x/WT1"]["status"] == "missing_all"
    assert by_uri["https://x/EDP1"]["status"] == "compliant"


# ── service requirements ──────────────────────────────────────────────────────
def test_service_requirements_ttl_survives_hostile_label(client, ws):
    """A quote/newline in a user label must be escaped, not break the Turtle."""
    spec = {
        "service_name": "Flex Service",
        "label": 'the "flexible" one\nsecond line',
        "requirements": [{"component": "Building", "attributes": ["floorArea"]}],
        "links": [{"domain": "Location", "range": "Building"}],
    }
    r = client.post(f"{B}/service/requirements", json=spec)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == "FlexService.ttl"
    g = rdflib.Graph()
    g.parse(data=body["ttl"], format="turtle")
    labels = [str(o) for o in g.objects(
        rdflib.URIRef("https://digicities.info/proj/testws/services/FlexService"),
        rdflib.RDFS.label)]
    assert labels == ['the "flexible" one\nsecond line']
    assert (ws / "services" / "FlexService.ttl").exists()


def test_service_template_yaml_nests_child_under_parent(client, ws):
    spec = {
        "service_name": "demo_service",
        "description": "d",
        "connection": {"url": "http://svc:9/run", "method": "POST"},
        "entries": [
            {"component_type": "Building", "attributes": ["label", "floorArea"]},
            {"component_type": "HeatPump", "parent": "Building", "attributes": ["copCurve"]},
        ],
    }
    r = client.post(f"{B}/service/template", json=spec)
    assert r.status_code == 200, r.text
    doc = yaml.safe_load(r.json()["yaml"])
    assert doc["service_name"] == "demo_service"
    assert doc["connection"]["url"] == "http://svc:9/run"
    sd = doc["scenario_data"]
    building = sd["building"]
    assert building["name"] == "Building.label"
    assert building["floorArea"] == "Building.floorArea"
    child = building["heatPump"]
    assert child["link"] == "CL.Building.HeatPump"
    assert child["template"]["copCurve"] == "HeatPump.copCurve"
    assert r.json()["saved"] == "DemoService.yaml"


# ── replica ───────────────────────────────────────────────────────────────────
def _declare(ws, spec):
    """Declare the spec's classes and attribute links in the workspace
    extension, as the Ontology Manager does before any replica is built."""
    from backend.replica_builder.draft import ReplicaDraft, build_workbook
    from workbook_schema import declare_workbook

    build_workbook(ReplicaDraft.from_request(spec["components"]), ws / "decl.xlsx")
    declare_workbook(ws / "decl.xlsx", ws)


def test_replica_generate_roundtrip_to_ttl(client, ws):
    spec = {
        "components": [{
            "cls": "Building",
            "columns": [{"name": "FloorArea", "type": "Physical", "unit": "M2"}],
            "rows": [{"id": "B1", "FloorArea": 120.5}],
        }],
        "persist": True,
    }
    _declare(ws, spec)
    r = client.post(f"{B}/replica/generate", json=spec)
    assert r.status_code == 200, r.text
    ttl = r.json()["ttl"]
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    uris = " ".join(str(s) for s in g.subjects())
    assert "Building/B1" in uris

    # persisted output is what Preview & Export serves
    got = client.get(f"{B}/replica/ttl").json()
    assert got["file"] == "testws.ttl"
    assert got["ttl"] == ttl

    cfg = client.get(f"{B}/replica/config").json()
    assert cfg == {"workspace": "testws",
                   "project_uri": "https://digicities.info/proj/testws"}


def test_replica_generate_refuses_an_undeclared_attribute_link(client, ws):
    # The converter never makes a predicate up from the sheet and column names.
    spec = {"components": [{
        "cls": "Building",
        "columns": [{"name": "FloorArea", "type": "Physical", "unit": "M2"}],
        "rows": [{"id": "B1", "FloorArea": 120.5}],
    }]}
    r = client.post(f"{B}/replica/generate", json=spec)
    assert r.status_code == 400
    assert "Building.FloorArea" in r.json()["detail"]


def test_replica_generate_refuses_unknown_column_type(client, ws):
    # An unknown type used to become a minted dici_onto:<type>Attribute class.
    spec = {"components": [{
        "cls": "Building",
        "columns": [{"name": "floorArea", "type": "decimal", "unit": "M2"}],
        "rows": [{"id": "B1", "floorArea": 120.5}],
    }]}
    r = client.post(f"{B}/replica/generate", json=spec)
    assert r.status_code == 400
    assert "unknown column type 'decimal'" in r.json()["detail"]


def test_replica_generate_requires_components(client, ws):
    assert client.post(f"{B}/replica/generate",
                       json={"components": []}).status_code == 400


def test_service_template_parse_round_trip_with_flavors(client, ws):
    """Generate a template with time-series flavors, parse it back: types,
    parents, flavors, and the connection block all survive."""
    conn = {"transport": "http", "url": "${WT_URL:-http://wt:8/run}", "method": "POST"}
    r = client.post(f"{B}/service/template", json={
        "service_name": "WindSvc",
        "description": "wind forecast",
        "connection": conn,
        "entries": [
            {"component_type": "GlobalWindAtlasSite", "attributes": ["Roughness"]},
            {"component_type": "WindTurbine", "parent": "GlobalWindAtlasSite",
             "attributes": {"HubHeight": ["Static"], "Power": ["Historic", "Future"]}},
        ],
    })
    assert r.status_code == 200
    text = r.json()["yaml"]
    # Flavored attributes emit time-series reference fields.
    assert "WindTurbine.Power.hasHistoricTimeSeriesReference" in text
    assert "WindTurbine.Power.hasFutureTimeSeriesReference" in text

    r = client.post(f"{B}/service/parse", json={"file": r.json()["saved"]})
    assert r.status_code == 200
    got = r.json()
    assert got["service_name"] == "WindSvc"
    assert got["connection"] == conn
    by_type = {e["component_type"]: e for e in got["entries"]}
    assert by_type["WindTurbine"]["parent"] == "GlobalWindAtlasSite"
    assert by_type["WindTurbine"]["link"] == "CL.GlobalWindAtlasSite.WindTurbine"
    assert sorted(by_type["WindTurbine"]["attributes"]["Power"]) == ["Future", "Historic"]
    assert by_type["GlobalWindAtlasSite"]["attributes"]["Roughness"] == ["Static"]


def test_service_template_path_keyed_multi_instance(client, ws):
    """Two entries of the same type under different paths — the Streamlit
    builder's path-keyed model — both land in the YAML and round-trip."""
    r = client.post(f"{B}/service/template", json={
        "service_name": "TwoBuildings",
        "entries": [
            {"component_type": "Location", "path": "location", "attributes": ["WeatherEPW"]},
            {"component_type": "Building", "path": "offices", "parent_path": "location",
             "attributes": ["GroundFloorArea"]},
            {"component_type": "Building", "path": "homes", "parent_path": "location",
             "attributes": ["NumberOfFloors"]},
        ],
    })
    assert r.status_code == 200
    text = r.json()["yaml"]
    assert "offices:" in text and "homes:" in text

    r = client.post(f"{B}/service/parse", json={"file": r.json()["saved"]})
    got = r.json()
    by_path = {e["path"]: e for e in got["entries"]}
    assert set(by_path) == {"location", "offices", "homes"}
    assert by_path["offices"]["component_type"] == "Building"
    assert by_path["homes"]["parent_path"] == "location"
    assert by_path["homes"]["link"] == "CL.Location.Building"


def test_service_template_root_reached_through_a_link(client, ws):
    """A root entry with link_from stays top-level but carries its link
    (`link: CL.Site.Unit`), and /parse gives link_from back for the builder."""
    r = client.post(f"{B}/service/template", json={
        "service_name": "SideBySide",
        "entries": [
            {"component_type": "Site", "path": "site", "attributes": ["Capacity"]},
            {"component_type": "Unit", "path": "units", "link_from": "Site",
             "attributes": ["Area"]},
        ],
    })
    assert r.status_code == 200, r.text
    import yaml as _yaml
    sd = _yaml.safe_load(r.json()["yaml"])["scenario_data"]
    assert sd["units"]["link"] == "CL.Site.Unit" and "units" not in sd["site"]

    got = client.post(f"{B}/service/parse", json={"file": r.json()["saved"]}).json()
    by_path = {e["path"]: e for e in got["entries"]}
    assert by_path["units"]["link_from"] == "Site" and by_path["units"]["parent_path"] is None
    assert by_path["site"]["link_from"] is None


def test_service_template_path_mode_validation(client, ws):
    base = {"service_name": "Bad", "entries": [
        {"component_type": "A", "path": "a", "attributes": ["x"]},
        {"component_type": "B", "attributes": ["y"]},
    ]}
    assert client.post(f"{B}/service/template", json=base).status_code == 400
    dup = {"service_name": "Bad", "entries": [
        {"component_type": "A", "path": "a", "attributes": ["x"]},
        {"component_type": "B", "path": "a", "attributes": ["y"]},
    ]}
    assert client.post(f"{B}/service/template", json=dup).status_code == 400


def test_service_fields_and_custom_names(client, ws):
    """/fields lists the customizable fields; custom_field_names renames the
    YAML key while the reference string stays canonical."""
    entries = [{"component_type": "WindTurbine", "path": "turbine",
                "attributes": {"Power": ["Historic"], "HubHeight": ["Static"]}}]
    r = client.post(f"{B}/service/fields", json={"entries": entries})
    assert r.status_code == 200
    by_key = {f["key"]: f for f in r.json()}
    assert by_key["turbine|Power|Historic"]["default_field"] == "Power_historic"
    assert by_key["turbine|HubHeight|Static"]["reference"] == "WindTurbine.HubHeight"

    r = client.post(f"{B}/service/template", json={
        "service_name": "Renamed", "entries": entries,
        "custom_field_names": {"turbine|Power|Historic": "generation_history"},
        "save": False,
    })
    text = r.json()["yaml"]
    assert "generation_history: WindTurbine.Power.hasHistoricTimeSeriesReference" in text
    assert "Power_historic" not in text


_ONTO_TTL = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dici_onto: <https://digicities.info/ontology#> .
dici_onto:HeatPump rdfs:subClassOf dici_onto:Component ; rdfs:label "HeatPump" .
dici_onto:HeatPumpAttribute rdfs:subClassOf dici_onto:ComponentAttribute .
dici_onto:hasHeatPumpAttribute rdfs:subPropertyOf dici_onto:hasComponentAttribute ;
    rdfs:domain dici_onto:HeatPump ; rdfs:range dici_onto:HeatPumpAttribute .
dici_onto:COP rdfs:subClassOf dici_onto:HeatPumpAttribute .
dici_onto:ThermalPower rdfs:subClassOf dici_onto:HeatPumpAttribute .
"""


def test_service_ontology_upload_parses_components(client, ws):
    r = client.post(f"{B}/service/ontology/upload",
                    files={"file": ("mini.ttl", _ONTO_TTL.encode(), "text/turtle")})
    assert r.status_code == 200
    got = r.json()
    comps = {c["component"]: c for c in got["components"]}
    assert "HeatPump" in comps
    assert comps["HeatPump"]["attributes"] == ["COP", "ThermalPower"]

    bad = client.post(f"{B}/service/ontology/upload",
                      files={"file": ("junk.ttl", b"not rdf at all {{{", "text/turtle")})
    assert bad.status_code == 400


def test_service_parse_rejects_bad_input(client, ws):
    assert client.post(f"{B}/service/parse", json={}).status_code == 400
    assert client.post(f"{B}/service/parse", json={"file": "nope.yaml"}).status_code == 404


# ── submission ────────────────────────────────────────────────────────────────
def _seed_template(ws, name="Svc.yaml", connection=None):
    d = ws / "services"
    d.mkdir(exist_ok=True)
    doc = {"service_name": "Svc"}
    if connection is not None:
        doc["connection"] = connection
    (d / name).write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_submission_lists_templates_and_scenarios(client, ws):
    _seed_template(ws, connection={"url": "${SVC_URL:-http://svc:9/run}", "method": "PUT"})
    (ws / "scenarios").mkdir()
    (ws / "scenarios" / "s1.ttl").write_text("# ttl", encoding="utf-8")

    t = client.get(f"{B}/submission/templates").json()
    assert len(t) == 1 and t[0]["file"] == "Svc.yaml" and t[0]["service_name"] == "Svc"
    # ${VAR:-default} is expanded for display/back-compat fields...
    assert t[0]["url"] == "http://svc:9/run" and t[0]["method"] == "PUT"
    assert t[0]["transport"] == "http" and t[0]["endpoint"] == "http://svc:9/run"
    # ...but the raw block is returned unexpanded for the connection editor.
    assert t[0]["connection"]["url"] == "${SVC_URL:-http://svc:9/run}"
    # Scenarios carry their builtForService tag (none here).
    assert client.get(f"{B}/submission/scenarios").json() == [
        {"file": "s1.ttl", "service": None}]


def test_submission_connection_writeback(client, ws):
    """PUT /connection swaps the block, preserves everything else."""
    _seed_template(ws, connection={"url": "http://old:1/run"})
    redis_conn = {"transport": "redis", "host": "h", "port": 6379,
                  "request_stream": "req.stream", "result_stream": "res.stream"}
    r = client.put(f"{B}/submission/connection",
                   json={"template_file": "Svc.yaml", "connection": redis_conn})
    assert r.status_code == 200
    doc = yaml.safe_load((ws / "services" / "Svc.yaml").read_text(encoding="utf-8"))
    assert doc["service_name"] == "Svc"
    assert doc["connection"] == redis_conn
    t = client.get(f"{B}/submission/templates").json()[0]
    assert t["transport"] == "redis"
    assert t["endpoint"] == "redis://h:6379/req.stream"


def test_submission_connection_save_writes_the_transport_only(client, ws):
    """A connection is how the service is called (transport, request/result
    streams). The live streams the model reads are components' live time series
    in the replica, never kept in the connection."""
    _seed_template(ws, connection={"transport": "redis", "result_stream": "out"})
    r = client.put(f"{B}/submission/connection", json={
        "template_file": "Svc.yaml",
        "connection": {"transport": "redis", "host": "h", "result_stream": "out2"}})
    assert r.status_code == 200
    doc = yaml.safe_load((ws / "services" / "Svc.yaml").read_text(encoding="utf-8"))
    assert doc["connection"] == {"transport": "redis", "host": "h", "result_stream": "out2"}


def test_submission_test_probe_degrades_cleanly(client, ws):
    """A connection without a URL reports unreachable, never 500s."""
    _seed_template(ws, connection={"transport": "http", "url": ""})
    r = client.post(f"{B}/submission/test", json={"template_file": "Svc.yaml"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    r = client.post(f"{B}/submission/test", json={"connection": {"url": ""}})
    assert r.json()["ok"] is False
    assert client.post(f"{B}/submission/test", json={}).status_code == 400


def test_submission_convert_materializes_thin_scenarios(client, ws):
    """A thin scenario carries no values — convert must merge the workspace
    replica first (like Streamlit and the agent do), so references resolve."""
    wt = "https://x/proj/testws/WindTurbine/W1"
    d = ws / "ingestion" / "output"
    d.mkdir(parents=True)
    (d / "replica.ttl").write_text(f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{wt}> a dici_onto:WindTurbine ;
    dici_onto:hasWindTurbineHubHeightAttribute <{wt}/HubHeight> ;
    dici_onto:hasWindTurbinePowerCurveAttribute <{wt}/PowerCurve> .
<{wt}/HubHeight> a dici_onto:HubHeight, dici_onto:PhysicalAttribute ; qudt:value 99.5 .
<{wt}/PowerCurve> a dici_onto:PowerCurve, dici_onto:CurveAttribute ;
    dici_onto:hasDataPoints "[[3.0, 0.0], [12.0, 2300.0]]" ;
    dici_onto:xUnitLabel "M-PER-SEC" ; dici_onto:yUnitLabel "KiloW" .
""", encoding="utf-8")
    (ws / "services").mkdir(exist_ok=True)
    (ws / "services" / "Wind.yaml").write_text(yaml.safe_dump({
        "service_name": "Wind",
        "scenario_data": {"turbines": {"link": "CL.Scenario.WindTurbine",
                                       "template": {"hub": "WindTurbine.HubHeight",
                                                    "curve": "WindTurbine.PowerCurve"}}},
    }), encoding="utf-8")
    r = client.post(f"{B}/scenario/build", json={
        "scenario_name": "Thin", "service_name": "Wind",
        "components": [{"uri": wt, "type": "WindTurbine", "label": "W1"}],
        "links": [{"source": "scenario", "target": wt, "link_type": "scenario_automatic"}]})
    assert r.status_code == 200
    r = client.post(f"{B}/submission/convert",
                    json={"template_file": "Wind.yaml", "scenario_file": "Thin.ttl"})
    assert r.status_code == 200
    got = r.json()
    assert got["validation"]["is_valid"] is True
    turbine = got["payload"]["scenario_data"]["turbines"][0]
    assert turbine["hub"] == 99.5
    # Curves convert as structured values (points + axis units), not null.
    assert turbine["curve"] == {"points": [[3.0, 0.0], [12.0, 2300.0]],
                                "x_unit": "M-PER-SEC", "y_unit": "KiloW"}


def test_submission_convert_ensures_template_aggregates(client, ws, monkeypatch):
    """The API convert (the React app's path) materializes the aggregates a
    template asks for before merging, like the Streamlit Convert tab — else
    `Tree.WeightMean` converts to null for every tree."""
    import apps.api.submission as sub
    import backend.collections as coll

    graph = object()
    seen = []
    monkeypatch.setattr(sub, "graph_client", lambda ctx: graph)
    monkeypatch.setattr(coll, "ensure_template_aggregates",
                        lambda c, ws_id, tmpl: seen.append((c, ws_id, tmpl)) or [])
    (ws / "services").mkdir(exist_ok=True)
    (ws / "services" / "Agg.yaml").write_text(yaml.safe_dump({
        "service_name": "Agg",
        "scenario_data": {"tree": {"uri": "Tree.URI", "WeightMean": "Tree.WeightMean"}},
    }), encoding="utf-8")
    (ws / "scenarios").mkdir(exist_ok=True)
    (ws / "scenarios" / "S.ttl").write_text("", encoding="utf-8")
    client.post(f"{B}/submission/convert",
                json={"template_file": "Agg.yaml", "scenario_file": "S.ttl"})
    assert seen and seen[0][0] is graph
    assert seen[0][2]["scenario_data"]["tree"]["WeightMean"] == "Tree.WeightMean"


def test_payload_validation_walks_implicit_root_lists():
    """The authoritative generator emits roots as plain blocks (no link:);
    the converter expands them into lists — the validator must walk the
    elements instead of flagging every root field as missing."""
    from backend.api_submission.validation import validate_payload

    template = {"service_name": "T",
                "scenario_data": {"roadNetwork": {
                    "name": "RoadNetwork.label", "Crs": "RoadNetwork.Crs"}}}
    payload = {"service_name": "T",
               "scenario_data": {"roadNetwork": [
                   {"name": "Zurich", "Crs": "Epsg2056"}]}}
    v = validate_payload(payload, template)
    assert v.is_valid and not v.missing_fields

    v = validate_payload({"service_name": "T", "scenario_data": {"roadNetwork": []}}, template)
    assert not v.is_valid


def test_submission_convert_returns_validation(client, ws):
    """Convert now reports the P0 validation result alongside the payload."""
    d = ws / "services"
    d.mkdir(exist_ok=True)
    (d / "Svc.yaml").write_text(yaml.safe_dump({
        "service_name": "Svc",
        "scenario_data": {"uri": "Scenario.URI", "ghost": "Phantom.Missing"},
    }), encoding="utf-8")
    client.post(f"{B}/scenario/build", json={
        "scenario_name": "V", "components": [{"uri": "https://x/WT/W1", "type": "WT"}]})
    r = client.post(f"{B}/submission/convert",
                    json={"template_file": "Svc.yaml", "scenario_file": "V.ttl"})
    assert r.status_code == 200
    got = r.json()
    assert got["payload"]["scenario_data"]["uri"].endswith("/V")
    v = got["validation"]
    # The unresolvable Phantom.Missing reference is reported by field path.
    assert "scenario_data.ghost" in v["unresolved_fields"] + v["missing_fields"]


def test_submission_submit_persists_result(client, ws):
    """Even a failed submission is recorded under results/<service>/ and
    readable through the results endpoints; traversal is rejected."""
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "payload": {"a": 1}, "scenario_file": "s1.ttl"})
    assert r.status_code == 200
    got = r.json()
    assert got["ok"] is False
    assert got["saved"].startswith("results/Svc/s1_")

    lst = client.get(f"{B}/submission/results").json()
    assert len(lst) == 1
    assert lst[0]["service_name"] == "Svc" and lst[0]["scenario_name"] == "s1"
    assert lst[0]["success"] is False

    content = client.get(f"{B}/submission/results/content",
                         params={"file": got["saved"]}).json()
    assert content["submitted_data"] == {"a": 1}
    assert content["error"]

    assert client.get(f"{B}/submission/results/content",
                      params={"file": "../services/Svc.yaml"}).status_code == 404
    assert client.get(f"{B}/submission/results/content",
                      params={"file": "results/Svc/../../services/Svc.yaml"}).status_code == 404


def test_submission_scenarios_carry_service_tag(client, ws):
    """A scenario built for a service reports it, so the UI can scope the
    submit list per service like the Streamlit tab."""
    client.post(f"{B}/scenario/build", json={
        "scenario_name": "ForWind", "service_name": "WindSvc",
        "components": [{"uri": "https://x/WT/W1", "type": "WT"}]})
    client.post(f"{B}/scenario/build", json={
        "scenario_name": "Untagged",
        "components": [{"uri": "https://x/WT/W1", "type": "WT"}]})
    got = client.get(f"{B}/submission/scenarios").json()
    assert {"file": "ForWind.ttl", "service": "WindSvc"} in got
    assert {"file": "Untagged.ttl", "service": None} in got


def test_submission_submit_stamps_service_name(client, ws):
    """A payload's service_name is overwritten with the template's, so a
    scenario converted under one name can't claim another service."""
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "scenario_file": "s.ttl",
        "payload": {"service_name": "SomethingElse",
                    "scenario_data": {"building": [{"uri": "urn:b1"}]}}})
    saved = r.json()["saved"]
    content = client.get(f"{B}/submission/results/content", params={"file": saved}).json()
    assert content["submitted_data"]["service_name"] == "Svc"


def test_submission_submit_persist_opt_out(client, ws):
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "payload": {"a": 1}, "persist": False})
    assert "saved" not in r.json()
    assert client.get(f"{B}/submission/results").json() == []


@pytest.mark.parametrize("payload", [
    {},
    {"service_name": "Svc", "description": "d"},
    {"service_name": "Svc", "scenario_data": {}},
    {"service_name": "Svc", "scenario_data": {"uri": "urn:s", "building": [], "site": []}},
    {"building": [], "site": []},
])
def test_submission_submit_refuses_hollow_payloads(client, ws, payload):
    """An empty payload, or one whose component arrays are all empty, is
    refused with 422 before anything is sent or persisted."""
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "scenario_file": "s.ttl", "payload": payload})
    assert r.status_code == 422, r.text
    assert "force=true" in r.json()["detail"]
    assert client.get(f"{B}/submission/results").json() == []


def test_submission_submit_force_sends_a_hollow_payload(client, ws):
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "payload": {"scenario_data": {"building": []}},
        "force": True, "persist": False})
    assert r.status_code == 200 and r.json()["ok"] is False   # sent (and failed to connect)


def test_submission_submit_accepts_partly_filled_payloads(client, ws):
    """Only ALL-empty arrays are hollow: one populated component list is enough."""
    _seed_template(ws, connection={"url": "http://localhost:59999/nope", "timeout": 2})
    r = client.post(f"{B}/submission/submit", json={
        "template_file": "Svc.yaml", "persist": False,
        "payload": {"scenario_data": {"building": [], "site": [{"uri": "urn:s1"}]}}})
    assert r.status_code == 200


def test_health_reports_the_baked_agent_commit(client, monkeypatch):
    """CI bakes AGENT_COMMIT into the image; /health surfaces it (same
    string-map schema, the key is simply absent when not set)."""
    monkeypatch.delenv("AGENT_COMMIT", raising=False)
    assert client.get("/health").json() == {"status": "ok"}
    monkeypatch.setenv("AGENT_COMMIT", "0123abcd")
    assert client.get("/health").json() == {"status": "ok", "agent_commit": "0123abcd"}


def test_service_mappings_degrade_without_graph(client, ws):
    r = client.get(f"{B}/service/mappings")
    assert r.status_code == 200
    assert r.json() == []


def test_submission_convert_404s(client, ws):
    r = client.post(f"{B}/submission/convert",
                    json={"template_file": "nope.yaml", "scenario_file": "s.ttl"})
    assert r.status_code == 404
    _seed_template(ws)
    r = client.post(f"{B}/submission/convert",
                    json={"template_file": "Svc.yaml", "scenario_file": "nope.ttl"})
    assert r.status_code == 404


def test_submission_submit_requires_connection_url(client, ws):
    _seed_template(ws)  # no connection block
    r = client.post(f"{B}/submission/submit",
                    json={"template_file": "Svc.yaml", "payload": {}})
    assert r.status_code == 400


# ── workspaces ────────────────────────────────────────────────────────────────
def test_list_workspaces_sorted_by_activity(client, ws, monkeypatch):
    import apps.api.registry_cache as RC

    other = types.SimpleNamespace(id="older", name="Older",
                                  graphdb_repository="", description="")
    monkeypatch.setattr(RC, "all_contexts", lambda: [other, _Ctx()])
    (ws / "afile.txt").write_text("x", encoding="utf-8")  # activity in testws only

    body = client.get("/api/workspaces").json()
    assert [w["id"] for w in body] == ["testws", "older"]
    assert body[0]["updated_at"] is not None
    assert body[1]["updated_at"] is None


def test_list_workspaces_no_params_is_a_plain_unpaginated_list(client, ws, monkeypatch):
    """The sidebar workspace switcher (and anything else calling with no query params)
    must keep getting every workspace as a plain array — pagination is opt-in."""
    import apps.api.registry_cache as RC

    fakes = [types.SimpleNamespace(id=f"w{i}", name=f"W{i}", graphdb_repository="", description="")
             for i in range(5)]
    monkeypatch.setattr(RC, "all_contexts", lambda: [_Ctx(), *fakes])
    body = client.get("/api/workspaces").json()
    assert isinstance(body, list) and len(body) == 6


def test_list_workspaces_paginates_when_asked(client, ws, monkeypatch):
    import apps.api.registry_cache as RC

    fakes = [types.SimpleNamespace(id=f"w{i}", name=f"W{i}", graphdb_repository="", description="")
             for i in range(5)]
    monkeypatch.setattr(RC, "all_contexts", lambda: [_Ctx(), *fakes])   # 6 total

    page1 = client.get("/api/workspaces?page=1&page_size=2").json()
    assert page1["total"] == 6 and page1["page"] == 1 and page1["page_size"] == 2
    assert len(page1["items"]) == 2

    page3 = client.get("/api/workspaces?page=3&page_size=2").json()
    assert len(page3["items"]) == 2
    seen = {w["id"] for w in page1["items"]} | {w["id"] for w in page3["items"]}
    assert len(seen) == 4                      # different workspaces on different pages

    page_last = client.get("/api/workspaces?page=99&page_size=2").json()
    assert page_last["items"] == []            # past the end → empty, not an error


def test_list_workspaces_sort_by_name(client, ws, monkeypatch):
    import apps.api.registry_cache as RC

    fakes = [types.SimpleNamespace(id="b", name="Bravo", graphdb_repository="", description=""),
             types.SimpleNamespace(id="a", name="Alpha", graphdb_repository="", description="")]
    monkeypatch.setattr(RC, "all_contexts", lambda: fakes)
    body = client.get("/api/workspaces?sort=name").json()
    assert [w["id"] for w in body] == ["a", "b"]


def test_workspace_info_exposes_metadata_and_stamp(client, ws):
    meta = ws / "workspace_meta"
    meta.mkdir()
    (meta / "metadata.json").write_text(
        json.dumps({"type": "District", "location": "Zurich"}), encoding="utf-8")
    body = client.get(f"{B}/info").json()
    assert body["type"] == "District"
    assert body["location"] == "Zurich"
    assert body["repository"] == "testws"
    assert body["updated_at"] is not None


def test_create_workspace_validates_and_echoes(client, monkeypatch):
    import backend.workspace as bw

    created = {}

    def fake_create(name, **kw):
        created["name"] = name
        created.update(kw)
        return types.SimpleNamespace(id="new-ws", name=name,
                                     graphdb_repository="new-ws",
                                     description=kw.get("description", ""))

    monkeypatch.setattr(bw, "create_workspace", fake_create)
    r = client.post("/api/workspaces", json={"name": "New WS", "description": "d"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "new-ws"
    assert created["provision_graph"] is True

    assert client.post("/api/workspaces", json={"name": "  "}).status_code == 400


# ── explorer/scenario palette endpoints (graph reads, stubbed) ────────────────
def test_scenario_instances_shapes_palette(client, ws, monkeypatch):
    import pandas as pd
    # The handler imports these lazily from backend.explorer at call time, so
    # that package (not the Streamlit shim) is the monkeypatch target.
    import backend.explorer as ce
    import apps.api.deps as deps

    monkeypatch.setattr(deps, "_client_for", lambda repo, url: object())
    monkeypatch.setattr(
        ce, "get_component_types_with_instances",
        lambda client: pd.DataFrame(
            [{"componentName": "Building",
              "componentType": "https://digicities.info/ontology#Building"}]))
    monkeypatch.setattr(
        ce, "get_component_data_unified",
        lambda client, name: ([{"URI": "https://p/Building/B1"}], []))
    monkeypatch.setattr(
        ce, "process_enhanced_component_data",
        lambda insts, attrs: pd.DataFrame(
            [{"URI": "https://p/Building/B1", "instance_id": "B1"}]))

    body = client.get(f"{B}/scenario/instances").json()
    assert body == [{"component": "Building",
                     "class": "https://digicities.info/ontology#Building",
                     "instances": [{"uri": "https://p/Building/B1", "label": "B1"}]}]


# ── agent (onboarder stubbed at the module seam) ──────────────────────────────
class _FakeAgentSession:
    instances: list["_FakeAgentSession"] = []

    def __init__(self, ws_id, ws_folder, ctx, repo_id, model=None):
        self.args = (ws_id, str(ws_folder), repo_id, model)
        self.ws_id = ws_id
        self.model = model
        self.state = types.SimpleNamespace(oa_messages=[])
        self.proposed = None
        _FakeAgentSession.instances.append(self)

    def snapshot(self):
        return {"messages": [], "stage": "start", "model": self.model,
                "chat_id": "chat-1"}

    def set_model(self, key):
        self.model = key

    def list_chats(self):
        return [{"id": "chat-1", "title": "T", "updated": 1.0}]

    def load_chat(self, chat_id):
        return self.snapshot()

    def send(self, text):
        return {"messages": [{"role": "user", "content": text}],
                "stage": "qa", "error": None}

    def send_stream(self, text):
        yield "token", "he"
        yield "token", "llo"
        yield "result", self.send(text)

    def propose(self, folder):
        self.proposed = str(folder)
        return {"messages": [], "stage": "gates", "error": None}

    def commands(self):
        return {"stage": "built", "commands": [
            {"key": "set_link", "area": "Replica", "form": "set link {A}→{B} to {predicate}",
             "usage": "set link <Class>→<Class> to <predicate>",
             "description": "Change the predicate of the link between two classes",
             "when_to_use": "The predicate that links two classes' instances is not the one "
                            "you want",
             "example": "set link WindTurbine→WindPark to hasLocation",
             "example_result": "a preview; reply yes to rebuild", "states": ["built"],
             "slots": [{"name": "predicate", "kind": "predicate", "label": "predicate",
                        "help": "A link predicate of the ontology",
                        "choices": [{"value": "hasLocation", "label": "hasLocation"},
                                    {"value": "partOf", "label": "partOf"}]}]}]}


@pytest.fixture()
def agent_env(monkeypatch, ws):
    _FakeAgentSession.instances = []
    mod = types.ModuleType("onboarding_agent.headless")
    mod.AgentSession = _FakeAgentSession
    mod.MODELS = [{"key": "sonnet", "label": "Sonnet"}]
    pkg = types.ModuleType("onboarding_agent")
    pkg.headless = mod
    monkeypatch.setitem(sys.modules, "onboarding_agent", pkg)
    monkeypatch.setitem(sys.modules, "onboarding_agent.headless", mod)
    # a clean session store per test (the real store is an LRU OrderedDict)
    import collections
    import apps.api.agent as agent_mod
    monkeypatch.setattr(agent_mod, "_SESSIONS", collections.OrderedDict())
    return agent_mod


def _start_session(client):
    r = client.post(f"{B}/agent/session", json={"model": "sonnet"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_agent_session_lifecycle(client, agent_env):
    assert client.get(f"{B}/agent/models").json() == [{"key": "sonnet", "label": "Sonnet"}]
    sid = _start_session(client)
    assert client.get(f"{B}/agent/state", params={"session_id": sid}).json()["stage"] == "start"
    assert client.post(f"{B}/agent/model",
                       json={"session_id": sid, "model": "opus"}).json() == {"model": "opus"}
    body = client.post(f"{B}/agent/message",
                       json={"session_id": sid, "text": "hi"}).json()
    assert body["stage"] == "qa" and body["error"] is None
    assert client.get(f"{B}/agent/chats").json()[0]["id"] == "chat-1"


def test_agent_commands_for_the_current_step(client, agent_env):
    """The React chat's command list: the agent registry's commands for the step
    the conversation is in, with slot choices."""
    sid = _start_session(client)
    body = client.get(f"{B}/agent/commands", params={"session_id": sid}).json()
    assert body["stage"] == "built"
    cmd = body["commands"][0]
    assert cmd["area"] == "Replica" and cmd["form"] == "set link {A}→{B} to {predicate}"
    assert cmd["when_to_use"] and cmd["example_result"] and cmd["slots"][0]["help"]
    assert cmd["slots"][0]["choices"][0] == {"value": "hasLocation", "label": "hasLocation"}
    assert client.get(f"{B}/agent/commands", params={"session_id": "nope"}).status_code == 404


def test_agent_unknown_session_404(client, agent_env):
    r = client.post(f"{B}/agent/message", json={"session_id": "nope", "text": "x"})
    assert r.status_code == 404


def test_agent_session_scoped_to_its_own_workspace(client, agent_env):
    """A session created for one workspace must not be usable through another
    workspace's URL — get_ctx only proves the caller may see the workspace NAMED IN
    THE URL, so _get() must independently check the session belongs to it. Regression
    for a real cross-workspace session hijack: a caller with legitimate access to
    workspace B could drive a session bound to a DIFFERENT (e.g. private) workspace A
    merely by knowing its session_id, bypassing A's visibility entirely."""
    foreign = _FakeAgentSession("some-other-private-workspace", "/tmp/x", None, "other-repo")
    agent_env._SESSIONS[foreign_id := "foreign-session-id"] = foreign

    for method, path, kwargs in [
        ("post", f"{B}/agent/message", dict(json={"session_id": foreign_id, "text": "x"})),
        ("get", f"{B}/agent/message/stream", dict(params={"session_id": foreign_id, "text": "x"})),
        ("post", f"{B}/agent/message/stream", dict(json={"session_id": foreign_id, "text": "x"})),
        ("get", f"{B}/agent/state", dict(params={"session_id": foreign_id})),
        ("get", f"{B}/agent/commands", dict(params={"session_id": foreign_id})),
        ("post", f"{B}/agent/model", dict(json={"session_id": foreign_id, "model": "opus"})),
        ("post", f"{B}/agent/mode", dict(json={"session_id": foreign_id, "mode": "auto"})),
    ]:
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 404, f"{method} {path} leaked a foreign session: {r.status_code} {r.text}"


def test_agent_stream_emits_tokens_then_result_then_done(client, agent_env):
    sid = _start_session(client)
    r = client.get(f"{B}/agent/message/stream",
                   params={"session_id": sid, "text": "hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [line.split(": ", 1)[1] for line in r.text.splitlines()
              if line.startswith("event: ")]
    assert events[:2] == ["token", "token"]
    assert events[-2:] == ["result", "done"]


def test_agent_upload_does_not_freeze_the_api(client, agent_env):
    """The upload's proposal (the model maps the folder, the harvest reads it)
    runs for minutes. Run on the event loop, it froze EVERY request: the health
    probe timed out, Kubernetes killed the container, and every chat session in
    memory was lost ("Stream error — is the API running?" until the module was
    reopened). Live 2026-10-02. The API must keep answering while it runs."""
    import threading
    import time

    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    started, release = threading.Event(), threading.Event()

    def slow_propose(folder):
        started.set()
        release.wait(5)
        return {"messages": [], "stage": "gates", "error": None}

    sess.propose = slow_propose
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", client.post(
        f"{B}/agent/upload", data={"session_id": sid},
        files={"file": ("guide.txt", b"description: x", "text/plain")})))
    t.start()
    try:
        assert started.wait(5), "the upload never reached the proposal"
        t0 = time.monotonic()
        health = client.get("/health")
        took = time.monotonic() - t0
        still_running = not release.is_set()
    finally:
        release.set()
        t.join(10)
    assert health.status_code == 200
    assert still_running and took < 2, f"/health waited {took:.1f}s for the upload"
    assert out["r"].status_code == 200


def test_no_route_runs_on_the_event_loop(api_app):
    """Every route is a plain ``def`` so FastAPI runs it in a worker thread. An
    ``async def`` route doing blocking work (an upload's minutes-long proposal,
    a workbook conversion, an ontology parse) stalls the single event loop:
    health probes time out and Kubernetes restarts the API, losing every chat
    session. Truly async code belongs in a helper awaited off the loop."""
    import inspect
    from fastapi.routing import APIRoute
    offenders = sorted(f"{sorted(r.methods)} {r.path}" for r in api_app.routes
                       if isinstance(r, APIRoute) and inspect.iscoroutinefunction(r.endpoint))
    assert not offenders, f"async routes block the event loop: {offenders}"


def test_agent_upload_single_file_makes_one_file_folder(client, agent_env):
    from pathlib import Path
    sid = _start_session(client)
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("model-guide.txt", b"description:\nwind model\n", "text/plain")})
    assert r.status_code == 200, r.text
    sess = _FakeAgentSession.instances[-1]
    folder = Path(sess.proposed)
    assert (folder / "model-guide.txt").read_text().startswith("description:")   # a one-file folder
    assert any("Uploaded `model-guide.txt`" in m[1] for m in sess.state.oa_messages)


def test_agent_upload_single_file_added_to_existing_folder(client, agent_env, tmp_path):
    from pathlib import Path
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    existing = tmp_path / "work"                       # simulate a prior (.zip) upload folder
    existing.mkdir()
    (existing / "config.yml").write_text("x: 1")
    sess._upload_folder = str(existing)
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("guide.txt", b"inputs:\nWindTurbine (a)\n", "text/plain")})
    assert r.status_code == 200, r.text
    assert (existing / "guide.txt").exists()           # added INTO the existing folder
    assert sess.proposed == str(existing)              # and re-proposed on it
    assert any("Added `guide.txt`" in m[1] for m in sess.state.oa_messages)


def test_agent_upload_after_a_restart_adds_to_the_kept_folder(client, agent_env, tmp_path):
    """The upload's temp dir is gone (server restart); the agent names the copy it
    kept in the workspace, and an added file goes there."""
    from pathlib import Path
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    kept = tmp_path / "ws" / "workspace_meta" / "onboarding_source"
    kept.mkdir(parents=True)
    (kept / "rooms.csv").write_text("room\n101\n")
    sess._upload_folder = str(tmp_path / "oa-zip-gone" / "x")
    sess.working_folder = lambda: str(kept)
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("guide.md", b"inputs: Room\n", "text/markdown")})
    assert r.status_code == 200, r.text
    assert (kept / "guide.md").exists() and sess.proposed == str(kept)
    assert not Path(sess._upload_folder).exists()


def test_a_fresh_chat_upload_starts_a_fresh_folder(client, agent_env, tmp_path):
    """Live 2026-10-05: a zip uploaded to a NEW chat on a workspace onboarded
    before was nested into the previous onboarding's kept copy. The agent's
    "replace" then wiped it with the old copy, and "append" re-read the old data
    with the new. A chat that is not in the middle of an onboarding gets a fresh
    folder, and the agent asks append-or-replace about the new upload alone."""
    import io, zipfile
    from pathlib import Path
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    kept = tmp_path / "ws" / "workspace_meta" / "onboarding_source"
    kept.mkdir(parents=True)
    (kept / "old.csv").write_text("a,1")
    sess.working_folder = lambda: str(kept)            # what a fresh session finds
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("new/onboarding_guide.md", "description: x")
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("new.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    folder = Path(sess.proposed)
    assert kept not in folder.parents and folder != kept
    assert (folder / "onboarding_guide.md").exists()
    assert not (kept / "new").exists()                  # the old copy is untouched


def test_a_restored_chat_with_a_mapping_still_adds_to_the_kept_folder(client, agent_env, tmp_path):
    """The other side: a chat restored after a restart carries its mapping, so a
    file it adds (a missing guide) belongs with that data."""
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    kept = tmp_path / "ws" / "workspace_meta" / "onboarding_source"
    kept.mkdir(parents=True)
    sess.state.oa_spec = {"components": []}
    sess.state.oa_stage = "gates"
    sess.working_folder = lambda: str(kept)
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("guide.md", b"inputs: Room", "text/markdown")})
    assert r.status_code == 200, r.text
    assert (kept / "guide.md").exists() and sess.proposed == str(kept)


def test_upload_can_defer_the_mapping_to_a_stream(client, agent_env):
    """Mapping a folder takes minutes and sends nothing meanwhile; networks cut
    requests that stay silent that long (live: 60 s), so the browser's upload
    errored while the server carried on. With propose=false the upload only
    stores the folder and returns at once; the mapping then runs over
    /propose/stream, which keeps the connection alive like the chat stream."""
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    r = client.post(f"{B}/agent/upload", data={"session_id": sid, "propose": "false"},
                    files={"file": ("guide.txt", b"description: x", "text/plain")})
    assert r.status_code == 200, r.text
    assert r.json()["pending_propose"] is True
    assert sess.proposed is None                       # nothing mapped yet

    r = client.get(f"{B}/agent/propose/stream", params={"session_id": sid})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
    assert events == ["result", "done"]
    assert sess.proposed and sess.proposed.endswith("x")   # the stored folder was mapped
    # nothing left waiting: a second stream is refused, not re-run
    assert client.get(f"{B}/agent/propose/stream", params={"session_id": sid}).status_code == 409


def test_agent_upload_rejects_empty_filename(client, agent_env):
    sid = _start_session(client)
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("", b"data", "application/octet-stream")})
    assert r.status_code in (400, 422)                 # no usable filename


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_agent_upload_proposes_from_extracted_folder(client, agent_env):
    sid = _start_session(client)
    payload = _zip_bytes({"proj/model.py": b"print(1)", "proj/data.csv": b"a,b"})
    r = client.post(f"{B}/agent/upload",
                    data={"session_id": sid},
                    files={"file": ("proj.zip", payload, "application/zip")})
    assert r.status_code == 200, r.text
    sess = agent_env._SESSIONS[sid]
    assert sess.proposed and sess.proposed.endswith("proj")
    assert sess.state.oa_messages[-1][1].startswith("📦 Uploaded")


def test_agent_upload_rejects_zip_slip(client, agent_env):
    sid = _start_session(client)
    payload = _zip_bytes({"../evil.txt": b"boom"})
    r = client.post(f"{B}/agent/upload",
                    data={"session_id": sid},
                    files={"file": ("evil.zip", payload, "application/zip")})
    assert r.status_code == 400
    assert "escapes" in r.json()["detail"]


def test_agent_upload_accepts_single_non_zip_file(client, agent_env):
    # A non-.zip file is no longer rejected — it becomes a one-file working folder.
    sid = _start_session(client)
    r = client.post(f"{B}/agent/upload",
                    data={"session_id": sid},
                    files={"file": ("notes.txt", b"x", "text/plain")})
    assert r.status_code == 200, r.text


def test_agent_stream_post_body_variant(client, agent_env):
    """Long messages ride in the POST body, not the query string (issue #14)."""
    sid = _start_session(client)
    r = client.post(f"{B}/agent/message/stream",
                    json={"session_id": sid, "text": "hi " * 2000})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [line.split(": ", 1)[1] for line in r.text.splitlines()
              if line.startswith("event: ")]
    assert events[-2:] == ["result", "done"]


def test_agent_session_store_evicts_oldest(client, agent_env, monkeypatch):
    """The session store is a bounded LRU: the cap evicts the least recently
    used session and releases its upload tmp dir."""
    monkeypatch.setenv("AGENT_SESSION_CAP", "2")
    disposed = []
    monkeypatch.setattr(agent_env, "_dispose", lambda s: disposed.append(s))

    s1 = _start_session(client)
    s2 = _start_session(client)
    # touch s1 so s2 becomes the LRU victim when s3 arrives
    client.get(f"{B}/agent/state", params={"session_id": s1})
    s3 = _start_session(client)

    assert set(agent_env._SESSIONS) == {s1, s3}
    assert len(disposed) == 1
    r = client.post(f"{B}/agent/message", json={"session_id": s2, "text": "x"})
    assert r.status_code == 404


# ── workspace delete ──────────────────────────────────────────────────────────
def test_delete_workspace_wraps_backend_and_reports(client, ws, monkeypatch):
    import apps.api.main as m

    calls = {}

    def fake_delete(ws_id, *, drop_dataset=True, ctx=None):
        calls["ws_id"] = ws_id
        calls["drop_dataset"] = drop_dataset
        return {"files_removed": True, "dataset_dropped": drop_dataset,
                "registry_entry_removed": False}

    monkeypatch.setattr("backend.workspace.delete_workspace", fake_delete)
    r = client.delete(f"{B}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspace"] == "testws"
    assert body["files_removed"] is True
    assert calls == {"ws_id": "testws", "drop_dataset": True}

    r = client.delete(f"{B}", params={"drop_dataset": "false"})
    assert r.status_code == 200
    assert calls["drop_dataset"] is False


def test_delete_workspace_drops_it_from_the_listing_cache(client, ws, monkeypatch):
    """The listing and lookups read the API's cache; a delete must update it
    at once (create already refreshes it), not at the next background refresh."""
    import apps.api.registry_cache as RC
    monkeypatch.setattr("backend.workspace.delete_workspace",
                        lambda ws_id, *, drop_dataset=True, ctx=None: {
                            "files_removed": True, "dataset_dropped": True,
                            "registry_entry_removed": False})
    forgotten = []
    monkeypatch.setattr(RC, "forget", forgotten.append)
    assert client.delete(f"{B}").status_code == 200
    assert forgotten == ["testws"]


def test_delete_workspace_protected_demo_is_403(client, ws, monkeypatch):
    from backend.workspace import WorkspaceProtected

    def refuse(ws_id, **kw):
        raise WorkspaceProtected(f"'{ws_id}' is a bundled demo")

    monkeypatch.setattr("backend.workspace.delete_workspace", refuse)
    r = client.delete(f"{B}")
    assert r.status_code == 403
    assert "demo" in r.json()["detail"]


def test_delete_workspace_stuck_files_is_409(client, ws, monkeypatch):
    monkeypatch.setattr(
        "backend.workspace.delete_workspace",
        lambda ws_id, **kw: {"files_removed": False, "dataset_dropped": True,
                             "registry_entry_removed": True})
    r = client.delete(f"{B}")
    assert r.status_code == 409
    assert "another program" in r.json()["detail"]


def test_workspace_summaries_carry_created_date_and_protection(client, ws, api_app, monkeypatch):
    import apps.api.registry_cache as RC
    from apps.api.deps import get_ctx

    meta = ws / "workspace_meta"
    meta.mkdir()
    (meta / "metadata.json").write_text(
        json.dumps({"created_date": "2026-08-21"}), encoding="utf-8")

    demo = types.SimpleNamespace(id="energy-simulation", name="Demo",
                                 graphdb_repository="", description="")
    # the fixture's ctx carries the storage read_workspace_metadata reads through
    ctx = api_app.dependency_overrides[get_ctx]()
    monkeypatch.setattr(RC, "all_contexts", lambda: [demo, ctx])

    by_id = {w["id"]: w for w in client.get("/api/workspaces").json()}
    assert by_id["testws"]["created_date"] == "2026-08-21"
    assert by_id["testws"]["protected"] is False
    assert by_id["energy-simulation"]["protected"] is True

    one = client.get(f"{B}").json()
    assert one["created_date"] == "2026-08-21"
    assert one["updated_at"] is not None


def test_agent_upload_second_zip_accumulates_into_folder(client, agent_env, tmp_path):
    import io, zipfile
    from pathlib import Path
    sid = _start_session(client)
    sess = _FakeAgentSession.instances[-1]
    existing = tmp_path / "work"                        # a prior working folder with data
    existing.mkdir()
    (existing / "first.txt").write_text("park one")
    sess._upload_folder = str(existing)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("park2/config.yml", "x: 2")          # a second folder of data
    r = client.post(f"{B}/agent/upload", data={"session_id": sid},
                    files={"file": ("park2.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert (existing / "first.txt").exists()            # original data kept
    assert (existing / "park2" / "config.yml").exists() # second zip nested in, not replacing
    assert sess.proposed == str(existing)               # re-proposed on the combined folder
    assert any("Added `park2.zip`" in m[1] for m in sess.state.oa_messages)


def _thin_scenario(ws, wt):
    """A thin scenario: a bare reference to a replica instance, no rdf:type."""
    from backend.scenario_builder import build_scenario_ttl, scenario_uri_for
    sc = scenario_uri_for(_Ctx.id, "Thin")
    (ws / "scenarios").mkdir(exist_ok=True)
    (ws / "scenarios" / "Thin.ttl").write_text(
        build_scenario_ttl("Thin", _Ctx.id, [wt], [(sc, wt)], scenario_uri=sc),
        encoding="utf-8")


def test_scenario_draft_types_thin_references_from_the_graph(client, ws, monkeypatch):
    import backend.scenario_builder.sync as sync_mod
    wt = "https://x/proj/testws/WindTurbine/W1"
    _thin_scenario(ws, wt)
    monkeypatch.setattr(sync_mod, "_instance_types", lambda c: ({wt: "WindTurbine"}, []))
    d = client.get(f"{B}/scenario/draft", params={"name": "Thin.ttl"}).json()
    assert d["components"][0]["type"] == "WindTurbine"


def test_scenario_draft_says_when_the_graph_cannot_type(client, ws, monkeypatch):
    import backend.scenario_builder.sync as sync_mod
    wt = "https://x/proj/testws/WindTurbine/W1"
    _thin_scenario(ws, wt)
    monkeypatch.setattr(sync_mod, "_instance_types",
                        lambda c: ({}, ["instance types (ConnectionError)"]))
    d = client.get(f"{B}/scenario/draft", params={"name": "Thin.ttl"}).json()
    # Untyped, never "WindTurbine" read off the IRI path, and said so.
    assert d["components"][0]["type"] is None
    assert any("ConnectionError" in w for w in d["warnings"])


def test_submission_convert_uses_the_workspace_schema(client, ws, monkeypatch):
    """The template names the superclass (CL.Scenario.Turbine); only the
    workspace extension says a WindTurbine IS a Turbine. Convert must read the
    extension, or the block comes back empty."""
    import apps.api.submission as sub
    monkeypatch.setattr(sub, "graph_client", lambda ctx: None)
    wt = "https://x/proj/testws/WindTurbine/W1"
    (ws / "ingestion" / "output").mkdir(parents=True)
    (ws / "ingestion" / "output" / "replica.ttl").write_text(f"""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
<{wt}> a dici_onto:WindTurbine ; dici_onto:hasAttribute <{wt}/HubHeight> .
<{wt}/HubHeight> a dici_onto:HubHeight, dici_onto:PhysicalAttribute ; qudt:value 99.5 .
""", encoding="utf-8")
    (ws / "ontology" / "extensions").mkdir(parents=True)
    (ws / "ontology" / "extensions" / "testws.ttl").write_text("""
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:WindTurbine rdfs:subClassOf dici_onto:Turbine .
dici_onto:HubHeight rdfs:subClassOf dici_onto:TurbineAttribute .
""", encoding="utf-8")
    (ws / "services").mkdir(exist_ok=True)
    (ws / "services" / "T.yaml").write_text(yaml.safe_dump({
        "service_name": "T",
        "scenario_data": {"turbines": {"link": "CL.Scenario.Turbine",
                                       "template": {"hub": "Turbine.HubHeight"}}},
    }), encoding="utf-8")
    from backend.scenario_builder import build_scenario_ttl, scenario_uri_for
    sc = scenario_uri_for(_Ctx.id, "S")
    (ws / "scenarios").mkdir(exist_ok=True)
    (ws / "scenarios" / "S.ttl").write_text(
        build_scenario_ttl("S", _Ctx.id, [wt], [(sc, wt)], scenario_uri=sc), encoding="utf-8")
    got = client.post(f"{B}/submission/convert",
                      json={"template_file": "T.yaml", "scenario_file": "S.ttl"}).json()
    assert got["payload"]["scenario_data"]["turbines"] == [{"hub": 99.5}]


def test_submission_convert_says_when_the_extension_is_unreadable(client, ws, monkeypatch):
    import apps.api.submission as sub
    monkeypatch.setattr(sub, "graph_client", lambda ctx: None)
    (ws / "ontology" / "extensions").mkdir(parents=True)
    (ws / "ontology" / "extensions" / "bad.ttl").write_text("this is not turtle @@@",
                                                            encoding="utf-8")
    (ws / "services").mkdir(exist_ok=True)
    (ws / "services" / "T.yaml").write_text(yaml.safe_dump({
        "service_name": "T", "scenario_data": {"uri": "Scenario.URI"}}), encoding="utf-8")
    from backend.scenario_builder import build_scenario_ttl, scenario_uri_for
    sc = scenario_uri_for(_Ctx.id, "S")
    (ws / "scenarios").mkdir(exist_ok=True)
    (ws / "scenarios" / "S.ttl").write_text(
        build_scenario_ttl("S", _Ctx.id, [], [], scenario_uri=sc), encoding="utf-8")
    got = client.post(f"{B}/submission/convert",
                      json={"template_file": "T.yaml", "scenario_file": "S.ttl"}).json()
    assert any("ontology extension could not be read" in w
               for w in got["validation"]["warnings"])
