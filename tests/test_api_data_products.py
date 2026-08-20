# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""HTTP contract tests for the data-products + files routers (Phase 5).

Router-test style (see tests/test_api_routers.py): a fake open workspace via
ctx override + USECASES_DIR pointed at tmp, real files on disk, no services.
The workspace ctx deliberately carries no ``storage`` attribute, so these
tests exercise the pure local-mode resolution (``ws_root`` wrapped as local
WorkspaceStorage) that must work without NextCloud.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

pytestmark = pytest.mark.api

FIXTURE_TTL = (Path(__file__).resolve().parent / "fixtures"
               / "use_case_data_product.ttl").read_text(encoding="utf-8")

CSV = "timestamp,demand_kw\n" + "\n".join(
    f"2026-01-01 {h:02d}:00,{10 + h}" for h in range(8)) + "\n"
GEOJSON = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [8.5, 47.4]},
     "properties": {"name": "site-a"}}]}


class _Ctx:
    id = "testws"
    name = "Test Workspace"
    graphdb_repository = "testws"
    description = "router-test workspace"


@pytest.fixture()
def ws(tmp_path, monkeypatch, api_app):
    """Fake open workspace + a private data product + an empty global library."""
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    monkeypatch.setenv("GLOBAL_DATA_PRODUCTS_DIR", str(tmp_path / "global_lib"))
    for var in ("NEXTCLOUD_BASIC_USERNAME", "NEXTCLOUD_BASIC_PASSWORD",
                "NEXTCLOUD_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    from apps.api.deps import get_ctx

    api_app.dependency_overrides[get_ctx] = lambda: _Ctx()
    root = tmp_path / _Ctx.id
    prod = root / "private_data_products" / "BatteryFleet"
    (prod / "resources").mkdir(parents=True)
    (prod / "BatteryFleet.ttl").write_text(FIXTURE_TTL, encoding="utf-8")
    (prod / "resources" / "demand.csv").write_text(CSV, encoding="utf-8",
                                                   newline="\n")
    (prod / "resources" / "site.geojson").write_text(
        json.dumps(GEOJSON), encoding="utf-8")
    (tmp_path / "global_lib").mkdir()
    return root


@pytest.fixture()
def client(api_client):
    return api_client


B = f"/api/workspaces/{_Ctx.id}"


# ── data products ─────────────────────────────────────────────────────────────
def test_list_data_products_local_mode(client, ws):
    body = client.get(f"{B}/data-products").json()
    assert body == [{
        "name": "BatteryFleet",
        "scope": "private",
        "components": body[0]["components"],  # fast size-based estimate
        "resources": 2,
        "ttl_path": "testws/private_data_products/BatteryFleet/BatteryFleet.ttl",
    }]
    assert body[0]["components"] >= 1


def test_list_includes_open_scope_products(client, ws, tmp_path):
    prod = tmp_path / "global_lib" / "SharedFleet"
    (prod / "resources").mkdir(parents=True)
    (prod / "SharedFleet.ttl").write_text(FIXTURE_TTL, encoding="utf-8")
    (prod / "resources" / "a.csv").write_text("x\n1\n", encoding="utf-8")

    body = client.get(f"{B}/data-products").json()
    assert [(p["name"], p["scope"]) for p in body] \
        == [("BatteryFleet", "private"), ("SharedFleet", "open")]
    assert body[1]["resources"] == 1


def test_data_product_detail_has_components_and_resources(client, ws):
    body = client.get(f"{B}/data-products/BatteryFleet").json()
    assert body["scope"] == "private"
    assert body["component_types"] == ["Battery", "Building"]
    assert body["component_count"] == 2
    battery = body["components"]["Battery"][0]
    assert battery["label"] == "Home Battery 1"
    assert battery["attributes"]["StorageCapacity"]["value"] == 13.5
    assert {r["name"] for r in body["resources"]} == {"demand.csv", "site.geojson"}

    assert client.get(f"{B}/data-products/Nope").status_code == 404
    # An explicit scope that doesn't hold the product is a 404 too.
    assert client.get(f"{B}/data-products/BatteryFleet",
                      params={"scope": "open"}).status_code == 404


def test_resource_endpoint_parses_csv_with_row_cap(client, ws, monkeypatch):
    import apps.api.data_products as dp

    monkeypatch.setattr(dp, "CSV_MAX_ROWS", 5)
    body = client.get(f"{B}/data-products/BatteryFleet/resource",
                      params={"path": "demand.csv"}).json()
    assert body["format"] == "csv"
    assert body["columns"] == ["timestamp", "demand_kw"]
    assert len(body["rows"]) == 5
    assert body["total_rows"] == 8
    assert body["truncated"] is True and body["max_rows"] == 5
    assert body["product"] == "BatteryFleet" and body["scope"] == "private"


def test_resource_endpoint_returns_geojson_object(client, ws):
    body = client.get(f"{B}/data-products/BatteryFleet/resource",
                      params={"path": "site.geojson"}).json()
    assert body["format"] == "geojson"
    assert body["content"] == GEOJSON
    assert body["summary"]["feature_count"] == 1


def test_resource_endpoint_uses_basename_only(client, ws):
    """Traversal-shaped paths reduce to their filename inside resources/."""
    body = client.get(f"{B}/data-products/BatteryFleet/resource",
                      params={"path": "../../../demand.csv"}).json()
    assert body["format"] == "csv"

    r = client.get(f"{B}/data-products/BatteryFleet/resource",
                   params={"path": "../../BatteryFleet.ttl"})
    assert r.status_code == 404  # the TTL is not in resources/


def test_resource_endpoint_404s_for_missing(client, ws):
    r = client.get(f"{B}/data-products/BatteryFleet/resource",
                   params={"path": "nope.csv"})
    assert r.status_code == 404


# ── files ─────────────────────────────────────────────────────────────────────
def test_files_lists_directories_then_files(client, ws):
    (ws / "notes.txt").write_text("hi", encoding="utf-8")
    body = client.get(f"{B}/files", params={"path": ""}).json()
    assert body["path"] == ""
    assert [(e["name"], e["type"]) for e in body["entries"]] \
        == [("private_data_products", "directory"), ("notes.txt", "file")]
    file_entry = body["entries"][1]
    assert file_entry["size"] == 2 and file_entry["mtime"] > 0

    sub = client.get(f"{B}/files",
                     params={"path": "private_data_products/BatteryFleet"}).json()
    assert sub["path"] == "private_data_products/BatteryFleet"
    assert {e["name"] for e in sub["entries"]} == {"BatteryFleet.ttl", "resources"}


def test_files_rejects_traversal_and_absolute_paths(client, ws):
    (ws.parent / "secret.txt").write_text("nope", encoding="utf-8")
    for bad in ("..", "../", "a/../../secret.txt", str(ws.parent / "secret.txt")):
        r = client.get(f"{B}/files", params={"path": bad})
        assert r.status_code == 400, bad
        assert "escapes" in r.json()["detail"]
        r = client.get(f"{B}/files/content", params={"path": bad})
        assert r.status_code == 400, bad


def test_files_404_and_not_a_directory(client, ws):
    assert client.get(f"{B}/files", params={"path": "nope"}).status_code == 404
    r = client.get(
        f"{B}/files",
        params={"path": "private_data_products/BatteryFleet/BatteryFleet.ttl"})
    assert r.status_code == 400
    assert "not a directory" in r.json()["detail"]


def test_files_content_serves_small_files_with_content_type(client, ws):
    r = client.get(
        f"{B}/files/content",
        params={"path": "private_data_products/BatteryFleet/resources/demand.csv"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text == CSV

    assert client.get(f"{B}/files/content",
                      params={"path": "nope.bin"}).status_code == 404
    assert client.get(f"{B}/files/content",
                      params={"path": "private_data_products"}).status_code == 400


def test_files_content_enforces_size_cap(client, ws, monkeypatch):
    import apps.api.files as files_mod

    monkeypatch.setattr(files_mod, "MAX_CONTENT_BYTES", 10)
    (ws / "big.bin").write_bytes(b"x" * 11)
    r = client.get(f"{B}/files/content", params={"path": "big.bin"})
    assert r.status_code == 413
    (ws / "ok.bin").write_bytes(b"x" * 10)
    assert client.get(f"{B}/files/content",
                      params={"path": "ok.bin"}).status_code == 200
