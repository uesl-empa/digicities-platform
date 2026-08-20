# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The Phase-3 backend moves: shims stay faithful, moved logic still works.

Four modules moved out of ``apps/streamlit/components/`` into ``backend/``
(NextCloud clients, service catalog, payload validation, display utils),
each leaving a re-export shim at the old import path. These tests pin:

- every old path hands back the *same objects* as the backend path;
- the moved logic behaves (validation rules, catalog listing, WebDAV
  request construction) without a Streamlit runtime.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shims: old import paths must yield the backend objects, not copies.
# ---------------------------------------------------------------------------

def test_service_catalog_shim_identity():
    import backend.service_catalog as new
    import components.service_catalog as old

    for name in ("ServiceRef", "list_workspace_services", "list_global_services",
                 "list_services", "services_by_name", "read_service_text"):
        assert getattr(old, name) is getattr(new, name), name


def test_nextcloud_shim_identity():
    import backend.nextcloud as new
    import components.nextcloud_client as old_client
    import components.nextcloud_global_client as old_global

    assert old_client.NextcloudClient is new.NextcloudClient
    assert old_client.create_client_from_env is new.create_client_from_env
    assert old_client.quick_read_timeseries is new.quick_read_timeseries
    assert old_global.NextcloudGlobalClient is new.NextcloudGlobalClient
    assert old_global.get_global_nextcloud_client is new.get_global_nextcloud_client


def test_validation_shim_identity():
    import backend.api_submission.validation as new
    import components.api_submission_module.validation as old

    assert old.validate_payload is new.validate_payload
    assert old.ValidationResult is new.ValidationResult
    # The Streamlit renderer stays on the shim side only.
    assert callable(old.render_validation)
    assert not hasattr(new, "render_validation")


def test_display_utils_shim_identity():
    import backend.scenario_builder.display_utils as new
    import components.scenario_builder.component_display_utils as old

    for name in ("get_uri_fragment", "format_ttl_component_for_display",
                 "get_nested_property_from_ttl_component"):
        assert getattr(old, name) is getattr(new, name), name


# ---------------------------------------------------------------------------
# validate_payload: the semantic-layer P0 rules.
# ---------------------------------------------------------------------------

TEMPLATE = {
    "service_name": "FlexibilityOptimizer",
    "required_attributes": ["PeakPower"],
    "scenario": {
        "uri": "Scenario.URI",
        "buildings": {
            "link": "CL.Scenario.Building",
            "template": {
                "floor_area": "Building.GroundFloorArea",
                "PeakPower": "Building.PeakPower",
            },
        },
    },
}


def _payload(floor_area=120.5, peak=7.2):
    return {
        "service_name": "FlexibilityOptimizer",
        "scenario": {
            "uri": "https://digicities.info/proj/ws/Scenario/S1",
            "buildings": [{"floor_area": floor_area, "PeakPower": peak}],
        },
    }


def test_validate_payload_all_resolved_is_good():
    from backend.api_submission.validation import validate_payload

    vr = validate_payload(_payload(), TEMPLATE)
    assert vr.is_valid
    assert vr.data_quality == "good"
    assert not vr.errors and not vr.warnings
    assert vr.placeholder_count == 0


def test_validate_payload_missing_optional_warns():
    from backend.api_submission.validation import validate_payload

    vr = validate_payload(_payload(floor_area=None), TEMPLATE)
    assert vr.is_valid                      # optional: not blocking
    assert vr.data_quality == "needs_review"
    assert vr.missing_fields == ["scenario.buildings[1].floor_area"]
    assert len(vr.warnings) == 1


def test_validate_payload_unresolved_required_blocks():
    from backend.api_submission.validation import validate_payload

    # The converter handed the literal reference back unchanged.
    vr = validate_payload(_payload(peak="Building.PeakPower"), TEMPLATE)
    assert not vr.is_valid
    assert vr.data_quality == "poor"
    assert vr.unresolved_fields == ["scenario.buildings[1].PeakPower"]
    assert vr.placeholder_count == 1
    assert any("Required attribute unresolved" in e for e in vr.errors)


def test_validate_payload_not_found_marker_counts_as_unresolved():
    from backend.api_submission.validation import validate_payload

    vr = validate_payload(_payload(floor_area="<Building.GroundFloorArea_not_found>"),
                          TEMPLATE)
    assert vr.is_valid                      # floor_area is optional
    assert vr.unresolved_fields == ["scenario.buildings[1].floor_area"]
    assert vr.data_quality == "needs_review"


def test_validate_payload_empty_link_expansion_is_an_error():
    from backend.api_submission.validation import validate_payload

    payload = _payload()
    payload["scenario"]["buildings"] = []
    vr = validate_payload(payload, TEMPLATE)
    assert not vr.is_valid
    assert any("no components found for link 'CL.Scenario.Building'" in e
               for e in vr.errors)


def test_validate_payload_empty_payload_is_an_error():
    from backend.api_submission.validation import validate_payload

    vr = validate_payload({"service_name": "FlexibilityOptimizer"}, TEMPLATE)
    assert not vr.is_valid
    assert any("empty" in e for e in vr.errors)


def test_validate_payload_literal_constants_need_no_resolving():
    from backend.api_submission.validation import validate_payload

    # service_name is a plain constant, not a CapitalisedComponent.attribute
    # reference, so echoing it back verbatim is fine.
    vr = validate_payload(_payload(), TEMPLATE)
    assert "service_name" not in "".join(vr.warnings + vr.errors)


# ---------------------------------------------------------------------------
# service_catalog: listing against a tmp workspace + global layout.
# ---------------------------------------------------------------------------

class FakeStorage:
    """Minimal ctx.storage lookalike over a local directory."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def glob(self, pattern: str):
        return [p.relative_to(self.root).as_posix()
                for p in sorted(self.root.glob(pattern))]

    def read_text(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")


@pytest.fixture()
def catalog_env(tmp_path, monkeypatch):
    """A workspace services/ folder + a local global services dir, NextCloud off."""
    import backend.service_catalog as sc

    ws = tmp_path / "workspace"
    (ws / "services").mkdir(parents=True)
    (ws / "services" / "WindForecasting.yaml").write_text(
        "service_name: WindForecasting\n", encoding="utf-8")
    (ws / "services" / "broken.yaml").write_text(
        "service_name: [unclosed\n", encoding="utf-8")

    global_dir = tmp_path / "global_services"
    global_dir.mkdir()
    (global_dir / "FlexOptimizer.yaml").write_text(
        "service_name: FlexOptimizer\n", encoding="utf-8")
    (global_dir / "wind_forecasting.yml").write_text(
        "service_name: WindForecasting\n", encoding="utf-8")

    monkeypatch.setenv("GLOBAL_SERVICES_DIR", str(global_dir))
    monkeypatch.setattr(sc, "_global_client", lambda: None)  # no NextCloud here
    storage = FakeStorage(ws)
    monkeypatch.setattr(sc, "_storage_provider", lambda: storage)
    return sc, storage


def test_list_workspace_services(catalog_env):
    sc, storage = catalog_env
    refs = sc.list_workspace_services(storage=storage)
    assert {(r.name, r.source, r.filename, r.ref) for r in refs} == {
        ("WindForecasting", "workspace", "WindForecasting.yaml",
         "services/WindForecasting.yaml"),
        ("Broken", "workspace", "broken.yaml", "services/broken.yaml"),
    }
    by_name = {r.name: r for r in refs}
    # Unparseable YAML still lists (name from filename), content stays None.
    assert by_name["WindForecasting"].content == {"service_name": "WindForecasting"}
    assert by_name["Broken"].content is None


def test_list_global_services_from_local_dir(catalog_env):
    sc, _ = catalog_env
    refs = sc.list_global_services()
    assert {(r.name, r.source) for r in refs} == {
        ("FlexOptimizer", "global"), ("WindForecasting", "global")}


def test_list_services_and_name_precedence(catalog_env):
    sc, _ = catalog_env
    refs = sc.list_services(global_first=True)
    assert [r.source for r in refs] == ["global", "global",
                                       "workspace", "workspace"]

    by_name = sc.services_by_name(global_first=True)
    # WindForecasting exists in both; global wins when global_first.
    assert by_name["WindForecasting"].source == "global"
    assert by_name["WindForecasting"].source != "workspace"

    by_name_ws = sc.services_by_name(global_first=False)
    assert by_name_ws["WindForecasting"].source == "workspace"


def test_read_service_text_both_sources(catalog_env):
    sc, storage = catalog_env
    ws_ref = next(r for r in sc.list_workspace_services(storage=storage)
                  if r.name == "WindForecasting")
    assert sc.read_service_text(ws_ref) == "service_name: WindForecasting\n"

    glob_ref = next(r for r in sc.list_global_services()
                    if r.name == "FlexOptimizer")
    assert sc.read_service_text(glob_ref) == "service_name: FlexOptimizer\n"


def test_workspace_listing_without_provider_is_empty(monkeypatch):
    """Headless with no provider registered: no storage, no services, no crash."""
    import backend.service_catalog as sc

    monkeypatch.setattr(sc, "_storage_provider", None)
    assert sc.list_workspace_services() == []


# ---------------------------------------------------------------------------
# NextcloudClient: request construction survives the move (HTTP mocked).
# ---------------------------------------------------------------------------

PROPFIND_XML = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/u/ws1/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/u/ws1/demand.csv</d:href>
    <d:propstat><d:prop>
      <d:getcontentlength>42</d:getcontentlength>
      <d:getlastmodified>Mon, 01 Jan 2026 00:00:00 GMT</d:getlastmodified>
      <d:getcontenttype>text/csv</d:getcontenttype>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        pass


@pytest.fixture()
def nc_client():
    from backend.nextcloud.client import NextcloudClient

    return NextcloudClient(base_url="https://nc.example", username="u",
                           password="p", workspace_id="ws1")


def test_nextcloud_url_and_auth_construction(nc_client):
    assert (nc_client._build_url(filename="demand.csv")
            == "https://nc.example/remote.php/dav/files/u/ws1/demand.csv")
    assert (nc_client._build_url(workspace_id="other")
            == "https://nc.example/remote.php/dav/files/u/other/")
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert nc_client.headers["Authorization"] == expected
    with pytest.raises(ValueError):
        nc_client.workspace_id = None
        nc_client._build_url()


def test_nextcloud_list_files_sends_propfind(nc_client, monkeypatch):
    import backend.nextcloud.client as mod

    seen = {}

    def fake_request(method, url, headers=None, data=None):
        seen.update(method=method, url=url, headers=headers)
        return FakeResponse(PROPFIND_XML, status_code=207)

    monkeypatch.setattr(mod.requests, "request", fake_request)
    files = nc_client.list_files()

    assert seen["method"] == "PROPFIND"
    assert seen["url"] == "https://nc.example/remote.php/dav/files/u/ws1/"
    assert seen["headers"]["Depth"] == "1"
    assert seen["headers"]["Authorization"].startswith("Basic ")
    assert files == [{"name": "demand.csv", "size": 42,
                      "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT",
                      "content_type": "text/csv"}]


def test_nextcloud_download_builds_file_url(nc_client, monkeypatch):
    import backend.nextcloud.client as mod

    seen = {}

    def fake_get(url, headers=None):
        seen["url"] = url
        return FakeResponse(b"a;b\n1;2\n")

    monkeypatch.setattr(mod.requests, "get", fake_get)
    content = nc_client.download_text_file("demand.csv")

    assert seen["url"] == "https://nc.example/remote.php/dav/files/u/ws1/demand.csv"
    assert content == "a;b\n1;2\n"
