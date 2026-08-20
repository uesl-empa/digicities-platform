# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The headless data-product processor + analyzer (``backend.data_products``).

Phase 5 (data-products half) moved ``DataProductProcessor`` out of the
Streamlit tree and extracted the pure resource-format parsing into
``backend.data_products.analyzer``. Drives both directly — no Streamlit, no
session state — against a tmp workspace layout with fixture product folders
(TTL + CSV/GeoJSON/EPW resources). Pins:

* listing/metadata/processing over WorkspaceStorage for both scopes
  (private = workspace tree, open = local global library);
* resource loading parsed per format (DataFrame / dict / text);
* the ``on_status`` seam: silent by default, events when wired;
* the analyzer's format sniffing/preview/summary helpers;
* the Streamlit shim subclasses the backend class (Phase 3/4 shim doctrine);
* the use-case loader's default hook now builds the backend processor.

NextCloud-only fallback paths are not exercised here (service-bound; the
storage paths above are the local-mode contract).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backend.data_products import DataProductProcessor, analyzer
from backend.workspace.storage import WorkspaceStorage

FIXTURE_TTL = (Path(__file__).resolve().parent / "fixtures"
               / "use_case_data_product.ttl").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_nextcloud_env(monkeypatch):
    """Local-mode contract: no ambient NextCloud creds may leak network calls
    into these tests (the legacy fallback is service-bound, marked-live land)."""
    for var in ("NEXTCLOUD_BASIC_USERNAME", "NEXTCLOUD_BASIC_PASSWORD",
                "NEXTCLOUD_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

CSV = "timestamp,demand_kw\n2026-01-01 00:00,12.5\n2026-01-01 01:00,11.0\n"
GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [8.54, 47.37]},
        "properties": {"name": "site-a", "kind": "office"},
    }],
}
EPW = "\n".join(
    ["LOCATION,Zurich,ZH,CHE,SRC,066600,47.37,8.55,1.0,556.0"]
    + [f"HEADER{i}" for i in range(2, 9)]
    + ["2026,1,1,1,60,A7A7,12.0,90,3.0,101000,0,0,300,120,80,40"] * 3
) + "\n"


def _make_product(folder: Path, name: str) -> None:
    prod = folder / name
    (prod / "resources").mkdir(parents=True)
    (prod / f"{name}.ttl").write_text(FIXTURE_TTL, encoding="utf-8")
    (prod / "resources" / "demand.csv").write_text(CSV, encoding="utf-8")
    (prod / "resources" / "site.geojson").write_text(json.dumps(GEOJSON), encoding="utf-8")
    (prod / "resources" / "weather.epw").write_text(EPW, encoding="utf-8")


@pytest.fixture()
def ws_tree(tmp_path: Path) -> Path:
    root = tmp_path / "test-ws"
    _make_product(root / "private_data_products", "BatteryFleet")
    return root


@pytest.fixture()
def global_lib(tmp_path: Path) -> Path:
    lib = tmp_path / "global_lib"
    _make_product(lib, "SharedWeather")
    return lib


@pytest.fixture()
def proc(ws_tree: Path, global_lib: Path) -> DataProductProcessor:
    return DataProductProcessor(
        workspace_id="test-ws",
        workspace_storage=WorkspaceStorage.local(str(ws_tree)),
        global_storage=WorkspaceStorage.local(str(global_lib)),
    )


# --------------------------------------------------------------- listings

def test_lists_private_and_open_folders(proc):
    assert proc.list_private_folders() == ["BatteryFleet"]
    assert proc.list_open_folders() == ["SharedWeather"]


def test_metadata_is_fast_and_scope_aware(proc):
    meta = proc.get_product_metadata("BatteryFleet", is_private=True)
    assert meta["name"] == "BatteryFleet"
    assert meta["is_private"] is True
    assert meta["folder_path"] == "test-ws/private_data_products/BatteryFleet"
    assert meta["ttl_path"].endswith("BatteryFleet/BatteryFleet.ttl")
    assert meta["resource_count"] == 3
    assert meta["ttl_size"] > 0

    open_meta = proc.get_product_metadata("SharedWeather", is_private=False)
    assert open_meta["is_private"] is False
    assert open_meta["folder_path"] == "SharedWeather"  # no workspace prefix

    assert proc.get_product_metadata("Nope", is_private=True) is None


# --------------------------------------------------------------- processing

def test_process_data_product_extracts_components_and_resources(proc):
    product = proc.process_data_product("BatteryFleet", is_private=True)
    assert product["type"] == "private"
    assert product["workspace_id"] == "test-ws"
    assert set(product["components"]) == {"Battery", "Building"}
    assert product["component_count"] == 2
    battery = product["components"]["Battery"][0]
    assert battery["label"] == "Home Battery 1"
    assert battery["attributes"]["StorageCapacity"]["value"] == 13.5
    names = {r["name"]: r["type"] for r in product["resources"]}
    assert names == {"demand.csv": "csv", "site.geojson": "geojson",
                     "weather.epw": "epw"}
    assert product["ttl_content"].startswith("#")

    assert proc.process_data_product("Nope", is_private=True) is None


def test_process_all_prefixes_keys_by_scope(proc):
    products = proc.process_all_data_products()
    assert set(products) == {"private:BatteryFleet", "global:SharedWeather"}
    assert products["global:SharedWeather"]["type"] == "global"
    assert products["global:SharedWeather"]["workspace_id"] is None


# ---------------------------------------------------------- resource loading

def test_load_resource_file_parses_known_formats(proc):
    product = proc.process_data_product("BatteryFleet", is_private=True)

    df = proc.load_resource_file(product, "demand.csv")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["timestamp", "demand_kw"]
    assert len(df) == 2

    geo = proc.load_resource_file(product, "site.geojson")
    assert geo == GEOJSON

    epw = proc.load_resource_file(product, "weather.epw")
    assert isinstance(epw, str) and epw.startswith("LOCATION,Zurich")


def test_load_missing_resource_reports_and_returns_none(ws_tree, global_lib):
    events = []
    proc = DataProductProcessor(
        workspace_id="test-ws",
        workspace_storage=WorkspaceStorage.local(str(ws_tree)),
        global_storage=WorkspaceStorage.local(str(global_lib)),
        on_status=lambda level, msg: events.append((level, msg)),
    )
    product = proc.process_data_product("BatteryFleet", is_private=True)
    assert proc.load_resource_file(product, "nope.csv") is None
    assert ("error", "Resource nope.csv not found in storage") in events


# ------------------------------------------------------------ on_status seam

def test_no_callback_default_is_silent(tmp_path, monkeypatch, capsys):
    """Degraded paths (no storage, no NextCloud creds) stay quiet and never
    raise when no on_status is wired — the Phase 4a callback contract."""
    monkeypatch.setenv("GLOBAL_DATA_PRODUCTS_DIR", str(tmp_path / "absent"))

    proc = DataProductProcessor()  # no workspace at all
    assert proc.list_private_folders() == []
    assert proc.list_open_folders() == []
    assert proc.get_product_metadata("X", is_private=False) is None
    assert proc.process_data_product("X", is_private=False) is None
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_on_status_reports_the_old_streamlit_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOBAL_DATA_PRODUCTS_DIR", str(tmp_path / "absent"))

    events = []
    DataProductProcessor(on_status=lambda level, msg: events.append((level, msg)))
    assert ("warning",
            "NextCloud credentials not found in environment variables "
            "(NEXTCLOUD_BASIC_USERNAME, NEXTCLOUD_BASIC_PASSWORD)") in events


def test_process_all_summary_goes_through_the_callback(proc):
    events = []
    proc.on_status = lambda level, msg: events.append((level, msg))
    proc.process_all_data_products()
    assert events[-1] == ("success", "✅ Loaded 2 data products")


# ------------------------------------------------------------------ analyzer

def test_detect_format_and_type_info():
    assert analyzer.detect_format("a/b/demand.CSV") == "csv"
    assert analyzer.detect_format("site.geojson") == "geojson"
    assert analyzer.detect_format("weather.epw") == "epw"
    assert analyzer.detect_format("README") == ""
    assert analyzer.get_type_info("csv")["emoji"] == "📊"
    assert analyzer.get_type_info("wat") == analyzer.TYPE_INFO["unknown"]


def test_group_resources_by_type():
    res = [{"name": "a.csv", "type": "csv"}, {"name": "b.csv", "type": "csv"},
           {"name": "c.epw", "type": "epw"}]
    grouped = analyzer.group_resources_by_type(res)
    assert sorted(grouped) == ["csv", "epw"]
    assert len(grouped["csv"]) == 2


def test_csv_preview_caps_rows_and_notes_the_cap():
    df = pd.DataFrame({"t": pd.date_range("2026-01-01", periods=10, freq="h"),
                       "v": range(10)})
    prev = analyzer.csv_preview(df, max_rows=4)
    assert prev["columns"] == ["t", "v"]
    assert len(prev["rows"]) == 4
    assert prev["total_rows"] == 10
    assert prev["truncated"] is True and prev["max_rows"] == 4
    assert prev["datetime_columns"] == ["t"]
    assert prev["numeric_columns"] == ["v"]

    full = analyzer.csv_preview(df, max_rows=100)
    assert full["truncated"] is False and len(full["rows"]) == 10


def test_geojson_summary_and_epw_parsing():
    summary = analyzer.geojson_summary(GEOJSON)
    assert summary == {"geojson_type": "FeatureCollection", "feature_count": 1,
                       "properties": ["kind", "name"]}

    header = analyzer.epw_head(EPW)
    assert header[0].startswith("LOCATION,Zurich")
    rows = analyzer.epw_sample_rows(EPW)
    assert rows and rows[0]["Month"] == "1" and rows[0]["Temperature"] == "12.0"


def test_resource_payload_tags_formats():
    df = pd.DataFrame({"v": [1, 2]})
    assert analyzer.resource_payload(df, "x.csv")["format"] == "csv"
    geo = analyzer.resource_payload(GEOJSON, "x.geojson")
    assert geo["format"] == "geojson" and geo["summary"]["feature_count"] == 1
    epw = analyzer.resource_payload(EPW, "x.epw")
    assert epw["format"] == "epw" and epw["header"]
    txt = analyzer.resource_payload("a" * 20_001, "x.txt", max_text=20_000)
    assert txt["truncated"] is True and len(txt["text"]) == 20_000
    blob = analyzer.resource_payload(b"\x00\x01", "x.parquet")
    assert blob["binary"] is True and blob["length"] == 2


# ---------------------------------------------------------------------- shim

def test_streamlit_shim_subclasses_the_backend_processor():
    """The old import path serves a subclass; the moved logic is not forked."""
    from components.data_products.data_loader import (
        DataProductProcessor as ShimProcessor,
    )

    assert issubclass(ShimProcessor, DataProductProcessor)
    assert ShimProcessor.process_data_product \
        is DataProductProcessor.process_data_product
    assert ShimProcessor.list_private_folders \
        is DataProductProcessor.list_private_folders
    assert ShimProcessor.load_resource_file \
        is DataProductProcessor.load_resource_file


def test_resource_analyzer_shim_delegates_pure_helpers():
    from components.data_products import resource_analyzer as shim

    assert shim._analyzer is analyzer


# ------------------------------------------- use-case loader default wiring

def test_use_case_loader_builds_backend_processor_by_default(
        ws_tree, global_lib, monkeypatch):
    """Phase 4a left the processor as an injected hook; after Phase 5 the
    backend loader wires the backend processor itself (explicit injection
    still wins — see tests/test_use_case_loader.py)."""
    from backend.scenario_builder.use_case_loader import NextCloudTTLUseCaseLoader

    monkeypatch.setenv("GLOBAL_DATA_PRODUCTS_DIR", str(global_lib))
    loader = NextCloudTTLUseCaseLoader(workspace_id="test-ws")
    assert isinstance(loader.data_processor, DataProductProcessor)
    # The local global library is reachable headlessly through the default.
    assert [dp["name"] for dp in loader.get_available_global_data_products()] \
        == ["SharedWeather"]
