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
def test_replica_generate_roundtrip_to_ttl(client, ws):
    spec = {
        "components": [{
            "cls": "Building",
            "columns": [{"name": "floorArea", "type": "decimal", "unit": "M2"}],
            "rows": [{"id": "B1", "floorArea": 120.5}],
        }],
        "persist": True,
    }
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


def test_replica_generate_requires_components(client, ws):
    assert client.post(f"{B}/replica/generate",
                       json={"components": []}).status_code == 400


# ── submission ────────────────────────────────────────────────────────────────
def _seed_template(ws, name="Svc.yaml", connection=None):
    d = ws / "services"
    d.mkdir(exist_ok=True)
    doc = {"service_name": "Svc"}
    if connection is not None:
        doc["connection"] = connection
    (d / name).write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_submission_lists_templates_and_scenarios(client, ws):
    _seed_template(ws, connection={"url": "http://svc:9/run", "method": "PUT"})
    (ws / "scenarios").mkdir()
    (ws / "scenarios" / "s1.ttl").write_text("# ttl", encoding="utf-8")

    t = client.get(f"{B}/submission/templates").json()
    assert t == [{"file": "Svc.yaml", "service_name": "Svc",
                  "url": "http://svc:9/run", "method": "PUT"}]
    assert client.get(f"{B}/submission/scenarios").json() == ["s1.ttl"]


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


def test_agent_unknown_session_404(client, agent_env):
    r = client.post(f"{B}/agent/message", json={"session_id": "nope", "text": "x"})
    assert r.status_code == 404


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
