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
    import apps.api.main as m

    other = types.SimpleNamespace(id="older", name="Older",
                                  graphdb_repository="", description="")
    monkeypatch.setattr(m, "load_registry", lambda: [other, _Ctx()])
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


def test_agent_upload_rejects_non_zip(client, agent_env):
    sid = _start_session(client)
    r = client.post(f"{B}/agent/upload",
                    data={"session_id": sid},
                    files={"file": ("notes.txt", b"x", "text/plain")})
    assert r.status_code == 400


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
