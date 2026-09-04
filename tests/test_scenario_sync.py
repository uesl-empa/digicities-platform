# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Scenario sync: a service change cascades onto the scenarios built for it.

Still-valid scenarios are untouched; partially-valid ones are archived and
rewritten thin (same URI/label/service); empty ones are archived and removed —
file and named graph both. The gate is the emitter's own completeness filter
with the service template's CURRENT requirements.
"""
from __future__ import annotations

import pytest

pytest.importorskip("rdflib")

import yaml  # noqa: E402

from backend.scenario_builder import build_scenario_ttl, scenario_uri_for  # noqa: E402
from backend.scenario_builder import sync as sync_mod  # noqa: E402
from backend.service_requirements.template import (  # noqa: E402
    build_service_template,
    entries_from_type_tree,
)
from backend.workspace.storage import WorkspaceStorage  # noqa: E402

PROJ = "https://digicities.info/proj/testws"
SC = scenario_uri_for("testws", "Baseline")


class _FakeClient:
    def __init__(self):
        self.updates: list[str] = []
        self.uploads: list[str] = []

    def sparql_update(self, statement):
        self.updates.append(statement)

    def upload_ttl(self, ttl_str, graph_name=None, replace_existing=False):
        self.uploads.append(ttl_str)
        return type("R", (), {"status_code": 204})()


def _write_service(storage, attrs):
    """A WindSvc template requiring the given WindTurbine attributes."""
    entries = entries_from_type_tree([
        ("Site", None, {"Roughness": ["Static"]}),
        ("WindTurbine", "Site", attrs),
    ])
    doc = build_service_template("WindSvc", entries, description="wind")
    storage.write_text("services/WindSvc.yaml", yaml.safe_dump(doc, sort_keys=False))
    return "services/WindSvc.yaml"


def _write_scenario(storage, name="Baseline", service="WindSvc", turbines=("T1", "T2")):
    site = f"{PROJ}/Site/Park1"
    comps = [site] + [f"{PROJ}/WindTurbine/{t}" for t in turbines]
    sc = scenario_uri_for("testws", name)
    links = [(sc, site)] + [(site, f"{PROJ}/WindTurbine/{t}") for t in turbines]
    ttl = build_scenario_ttl(scenario_name=name, workspace_id="testws",
                             components=comps, links=links,
                             service_name=service, scenario_uri=sc)
    storage.write_text(f"scenarios/{name}.ttl", ttl)
    return f"scenarios/{name}.ttl"


def _graph_attrs(values_by_uri):
    """attach_graph_attributes stand-in: serve attribute values from a dict."""
    def fake(client, comps):
        for c in comps:
            found = values_by_uri.get(c["uri"])
            if found:
                c["attributes"] = {k: {"value": v} for k, v in found.items()}
    return fake


@pytest.fixture()
def storage(tmp_path):
    return WorkspaceStorage.local(str(tmp_path))


def _all_attrs():
    return {
        f"{PROJ}/Site/Park1": {"Roughness": 1.0},
        f"{PROJ}/WindTurbine/T1": {"HubHeight": 85},
        f"{PROJ}/WindTurbine/T2": {"HubHeight": 90},
    }


def test_still_valid_scenarios_untouched(storage, monkeypatch):
    svc = _write_service(storage, {"HubHeight": ["Static"]})
    rel = _write_scenario(storage)
    before = storage.read_text(rel)
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", _graph_attrs(_all_attrs()))
    client = _FakeClient()
    rep = sync_mod.sync_scenarios_for_service(storage, client, svc)
    (entry,) = rep["scenarios"]
    assert entry["action"] == "unchanged"
    assert storage.read_text(rel) == before
    assert not client.updates and not client.uploads
    assert not storage.glob("scenarios/_archive/*.ttl")


def test_partially_valid_rewritten_thin_with_archive(storage, monkeypatch):
    svc = _write_service(storage, {"HubHeight": ["Static"]})
    rel = _write_scenario(storage)
    attrs = _all_attrs()
    del attrs[f"{PROJ}/WindTurbine/T2"]                     # T2 lost its HubHeight
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", _graph_attrs(attrs))
    client = _FakeClient()
    rep = sync_mod.sync_scenarios_for_service(storage, client, svc)
    (entry,) = rep["scenarios"]
    assert entry["action"] == "rewritten" and "2/3" in entry["detail"]
    assert any("T2" in d and "HubHeight" in d for d in entry["dropped"])
    # Previous version archived, new file is thin with the kept set only.
    (arch,) = storage.glob("scenarios/_archive/*.ttl")
    assert "WindTurbine/T2" in storage.read_text(arch)
    new = storage.read_text(rel)
    assert "WindTurbine/T1" in new and "WindTurbine/T2" not in new
    assert f"<{SC}> a dici_onto:Scenario" in new            # same URI preserved
    assert 'dici_onto:builtForService "WindSvc"' in new
    # Graph mirrored: scoped remove + re-push.
    assert any(SC in u for u in client.updates) and client.uploads


def test_nothing_valid_archives_and_removes(storage, monkeypatch):
    svc = _write_service(storage, {"HubHeight": ["Static"], "PowerCurve": ["Static"]})
    rel = _write_scenario(storage)
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", _graph_attrs({}))
    client = _FakeClient()
    rep = sync_mod.sync_scenarios_for_service(storage, client, svc)
    (entry,) = rep["scenarios"]
    assert entry["action"] == "removed"
    assert not storage.exists(rel)
    assert storage.glob("scenarios/_archive/*.ttl")
    assert any(SC in u for u in client.updates)             # graph cleaned up
    assert not client.uploads


def test_other_services_scenarios_ignored(storage, monkeypatch):
    svc = _write_service(storage, {"HubHeight": ["Static"]})
    _write_scenario(storage, name="Other", service="OtherSvc")
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", _graph_attrs({}))
    rep = sync_mod.sync_scenarios_for_service(storage, _FakeClient(), svc)
    assert rep["scenarios"] == []                           # not tagged for WindSvc


# ── REST contract ─────────────────────────────────────────────────────────────
pytestmark_api = pytest.mark.api


@pytest.mark.api
def test_rest_sync_endpoint(tmp_path, monkeypatch, api_app, api_client):
    """POST /scenario/sync resolves the service like /scenario/requirements and
    returns the sync report. Identity-only requirements keep the scenario valid
    without touching the graph, so the contract is pinned network-free."""
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx

    class _Ctx:
        id = "testws"
        name = "Test"
        graphdb_repository = "testws"
        description = ""

    root = tmp_path / "testws"
    root.mkdir()
    ctx = _Ctx()
    ctx.storage = WorkspaceStorage.local(str(root))
    api_app.dependency_overrides[get_ctx] = lambda: ctx

    # A service whose only requirements are identity fields (uri/name) — every
    # referenced component satisfies them synthetically.
    entries = entries_from_type_tree([("Site", None, {})])
    ctx.storage.write_text("services/WindSvc.yaml", yaml.safe_dump(
        build_service_template("WindSvc", entries, description="wind"), sort_keys=False))
    _write_scenario(ctx.storage, turbines=())
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", lambda client, comps: None)

    r = api_client.post("/api/workspaces/testws/scenario/sync", json={"service": "WindSvc"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service"] == "WindSvc"
    assert [s["action"] for s in body["scenarios"]] == ["unchanged"]

    r = api_client.post("/api/workspaces/testws/scenario/sync", json={"service": "NoSuch"})
    assert r.status_code == 404


def test_dry_run_reports_without_touching_anything(storage, monkeypatch):
    svc = _write_service(storage, {"HubHeight": ["Static"]})
    rel = _write_scenario(storage)
    before = storage.read_text(rel)
    attrs = _all_attrs()
    del attrs[f"{PROJ}/WindTurbine/T2"]
    monkeypatch.setattr(sync_mod, "attach_graph_attributes", _graph_attrs(attrs))
    client = _FakeClient()
    rep = sync_mod.sync_scenarios_for_service(storage, client, svc, dry_run=True)
    (entry,) = rep["scenarios"]
    assert entry["action"] == "rewritten" and "would keep 2/3" in entry["detail"]
    assert any("T2" in d for d in entry["dropped"])
    # NOTHING happened: file identical, no archive, no graph traffic.
    assert storage.read_text(rel) == before
    assert not storage.glob("scenarios/_archive/*.ttl")
    assert not client.updates and not client.uploads
