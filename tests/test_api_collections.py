# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Collections REST endpoints: routing, name resolution, IRI expansion,
error mapping. Backend functions are monkeypatched — the statistics logic has
its own suite (test_collections.py); this pins the HTTP contract.

Skips when fastapi isn't installed (it's an apps/api extra, not a platform
dependency)."""
from __future__ import annotations

import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from apps.api import collections as api_collections  # noqa: E402
from apps.api.deps import get_ctx  # noqa: E402
from apps.api.main import app  # noqa: E402


class _Ctx:
    id = "demo"
    graphdb_repository = "demo"


COLL = "https://digicities.info/proj/demo/collections/FloorAreaSet"
LISTING = pd.DataFrame([{
    "collection": COLL,
    "kind": "https://digicities.info/ontology#Set",
    "attrType": "https://digicities.info/ontology#FloorArea",
    "groupedBy": None, "dataset": None, "computedAt": "2026-08-18T12:00:00Z",
}])


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_ctx] = lambda: _Ctx()
    monkeypatch.setattr(api_collections, "graph_client", lambda ctx: object())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_index_and_detail(client, monkeypatch):
    monkeypatch.setattr(api_collections, "list_collections", lambda c: LISTING)
    monkeypatch.setattr(api_collections, "set_statistics", lambda c, i: pd.DataFrame(
        [{"set": COLL, "groupKey": None,
          "statistic": "https://digicities.info/ontology#mean", "value": "252.5"}]))
    monkeypatch.setattr(api_collections, "set_bins", lambda c, i: pd.DataFrame())
    monkeypatch.setattr(api_collections, "member_count", lambda c, i: 12)

    r = client.get("/api/workspaces/demo/collections")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "FloorAreaSet"
    assert r.json()[0]["kind"] == "Set"

    r = client.get("/api/workspaces/demo/collections/FloorAreaSet")
    assert r.status_code == 200
    body = r.json()
    assert body["member_count"] == 12
    assert body["statistics"][0]["value"] == "252.5"

    r = client.get("/api/workspaces/demo/collections/Nope")
    assert r.status_code == 404


def test_materialize_expands_local_names(client, monkeypatch):
    calls = {}

    def fake_grouped(c, ws, attr, group, dataset, project_statistics):
        calls.update(ws=ws, attr=attr, group=group, dataset=dataset,
                     stats=project_statistics)
        return "https://digicities.info/proj/demo/collections/FloorAreaByDistrict"

    monkeypatch.setattr(api_collections, "materialize_grouped_set", fake_grouped)
    r = client.post("/api/workspaces/demo/collections",
                    json={"attribute": "FloorArea", "group_by": "District",
                          "statistics": ["mean", "sum"]})
    assert r.status_code == 201
    assert r.json()["name"] == "FloorAreaByDistrict"
    assert calls["attr"] == "https://digicities.info/ontology#FloorArea"
    assert calls["group"] == "https://digicities.info/ontology#District"
    assert calls["dataset"] is None
    assert calls["stats"] == ("mean", "sum")


def test_materialize_collection_error_maps_to_422(client, monkeypatch):
    from backend.collections import CollectionError

    def boom(c, ws, attr, dataset):
        raise CollectionError("empty value set — nothing to aggregate")

    monkeypatch.setattr(api_collections, "materialize_set", boom)
    r = client.post("/api/workspaces/demo/collections",
                    json={"attribute": "FloorArea"})
    assert r.status_code == 422
    assert "nothing to aggregate" in r.json()["detail"]


def test_delete_resolves_name(client, monkeypatch):
    deleted = {}
    monkeypatch.setattr(api_collections, "list_collections", lambda c: LISTING)
    monkeypatch.setattr(api_collections, "delete_collection",
                        lambda c, iri: deleted.update(iri=iri))
    r = client.delete("/api/workspaces/demo/collections/FloorAreaSet")
    assert r.status_code == 200
    assert deleted["iri"] == COLL


def test_options_shape(client, monkeypatch):
    monkeypatch.setattr(api_collections, "workspace_attribute_types",
                        lambda c: pd.DataFrame([{"attrType": "x", "label": None,
                                                 "instanceCount": "3"}]))
    monkeypatch.setattr(api_collections, "workspace_component_types",
                        lambda c: pd.DataFrame())
    monkeypatch.setattr(api_collections, "workspace_datasets",
                        lambda c: pd.DataFrame())
    r = client.get("/api/workspaces/demo/collections/options")
    assert r.status_code == 200
    body = r.json()
    assert body["attribute_types"][0]["attrType"] == "x"
    assert body["component_types"] == [] and body["datasets"] == []
