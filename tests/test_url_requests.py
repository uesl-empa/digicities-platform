# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Services that read their request from the URL and hand results back as a link to
a file. Everything here goes over a real local HTTP server."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from backend.api_submission.connection import resolve_connection, submit_via_connection, test_connection as probe
from backend.api_submission.result_files import fetch_result_files
from backend.api_submission.transports import safe_get, submit_http, url_records
from backend.service_requirements.contract import output_problems, parse_outputs
from backend.service_requirements.requirements import requirements_ttl

CSV = b"timestamp,demand_kwh,pv_kwh\n2023-01-01T00:00,1.5,0\n2023-01-01T01:00,1.4,0\n"


class _Service(BaseHTTPRequestHandler):
    """Runs an area on /simulate/<area>, overwriting that area's one result file."""
    seen: list = []
    files: dict = {}

    def log_message(self, *_):
        pass

    def _send(self, status, body, kind="application/json", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        type(self).seen.append(("HEAD", self.path, {}))
        self._send(405, b"")

    def do_GET(self):
        url = urlsplit(self.path)
        parts = url.path.strip("/").split("/")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        type(self).seen.append(("GET", self.path, dict(self.headers)))
        if parts[0] == "simulate":
            area = parts[1]
            if area == "BAD":
                return self._send(500, b'{"detail": "no such area"}')
            name = f"profile_{area}.csv"
            # The file's content says which run wrote it: the next run overwrites it.
            type(self).files[name] = CSV + f"# fraction {query.get('fraction')}\n".encode()
            return self._send(200, json.dumps({"status": "success", "area": area,
                                               "result": {"url": f"/files/{name}"}}).encode())
        if parts[0] == "files":
            if parts[1] not in type(self).files:
                return self._send(404, b"gone")
            return self._send(200, type(self).files[parts[1]], "text/csv")
        if parts[0] == "to-metadata":
            return self._send(302, b"", headers=[("Location", "http://169.254.169.254/latest")])
        return self._send(404, b"{}")


@pytest.fixture()
def service():
    _Service.seen, _Service.files = [], {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def _contract(url, **conn):
    return {
        "service_name": "AreaProfile",
        "connection": {"url": f"{url}/simulate/{{area}}", "method": "GET", "timeout": 5, **conn},
        "scenario_data": {"area_block": {"area": "Area.label", "fraction": "Area.Fraction"}},
        "outputs": [{"component": "Area", "file_field": "result.url", "identified_by": "area",
                     "attributes": {"demand_kwh": "Area.Demand", "pv_kwh": "Area.Pv"}}],
    }


def _saver(kept):
    def save(name, data):
        kept[name] = data
        return f"results/{name}"
    return save


# ── the request in the URL ───────────────────────────────────────────────────
def test_records_one_per_component_and_shared_fields_go_with_each():
    assert url_records({"service_name": "S", "description": "d", "units": {"a": "KiloW"},
                        "scenario_data": {"fraction": 0.5, "areas": [{"area": "A"}, {"area": "B"}]}}) == [
        {"fraction": 0.5, "area": "A"}, {"fraction": 0.5, "area": "B"}]
    # No list is one call; a field nearer the component wins.
    assert url_records({"scenario_data": {"uri": "run", "park": {"uri": "p", "x": 1}}}) == [{"uri": "p", "x": 1}]


@pytest.mark.parametrize("payload, names", [
    ({"a": [{"x": 1}], "b": [{"y": 1}]}, "a, b"),
    ({"a": [{"x": [{"y": 1}]}]}, "a.x"),
    ({"a": [1, 2, 3]}, "`a`"),
])
def test_what_a_url_cannot_carry_is_refused_by_name(payload, names):
    with pytest.raises(ValueError, match=names):
        url_records(payload)


def test_get_fills_the_path_and_sends_the_rest_as_the_query(service):
    tr = submit_http({"service_name": "S", "scenario_data": {"fraction": 0.5, "areas": [{"area": "1 A/B"}]}},
                     url=f"{service}/simulate/{{area}}", method="get", timeout=5)
    assert tr.success and tr.status_code == 200
    assert _Service.seen[0][1] == "/simulate/1%20A%2FB?fraction=0.5"
    call = tr.response_data["calls"][0]
    assert call["request"] == {"fraction": 0.5, "area": "1 A/B"} and call["response"]["status"] == "success"


def test_get_makes_one_call_per_component_and_a_failure_does_not_stop_the_others(service):
    tr = submit_http({"areas": [{"area": "A"}, {"area": "BAD"}, {"area": "C"}]},
                     url=f"{service}/simulate/{{area}}", method="GET", timeout=5)
    assert not tr.success and tr.status_code == 500
    assert [c["status_code"] for c in tr.response_data["calls"]] == [200, 500, 200]
    assert tr.error_message.startswith("1 of 3 calls failed")


def test_get_stops_when_nothing_answers():
    tr = submit_http({"areas": [{"area": "A"}, {"area": "B"}]},
                     url="http://127.0.0.1:9/simulate/{area}", method="GET", timeout=2)
    assert not tr.success and len(tr.response_data["calls"]) == 1
    assert "1 of 2 calls failed, and 1 were not made" in tr.error_message


def test_a_field_the_url_needs_and_the_request_lacks_sends_nothing(service):
    tr = submit_http({"areas": [{"area": "A"}, {"fraction": 1}]},
                     url=f"{service}/simulate/{{area}}", method="GET", timeout=5)
    assert not tr.success and "needs area" in tr.error_message and _Service.seen == []


def test_a_url_field_survives_the_environment_expansion(monkeypatch):
    monkeypatch.delenv("MODEL_URL", raising=False)
    url = "${MODEL_URL:-http://fallback:1}/simulate/{pc6}"
    assert resolve_connection({"url": url, "method": "GET"})["url"] == "http://fallback:1/simulate/{pc6}"
    monkeypatch.setenv("MODEL_URL", "http://real:2")
    assert resolve_connection({"url": url, "method": "GET"})["url"] == "http://real:2/simulate/{pc6}"


def test_post_still_rejects_other_methods():
    assert "Unsupported" in submit_http({}, url="http://x", method="DELETE").error_message


def test_probe_uses_head_before_the_first_field_so_it_starts_no_run(service):
    got = probe({"url": f"{service}/simulate/{{area}}", "method": "GET"})
    assert got["ok"] and got["status_code"] == 405
    assert _Service.seen[0][:2] == ("HEAD", "/simulate/")


def test_a_link_local_address_is_refused_directly_and_by_redirect(service):
    tr = submit_http({"a": 1}, url="http://169.254.169.254/latest", method="GET", timeout=2)
    assert "link-local" in tr.error_message
    with pytest.raises(Exception, match="link-local"):
        safe_get(f"{service}/to-metadata", timeout=5)
    assert all("169.254" not in seen[1] for seen in _Service.seen)


# ── results in a linked file ─────────────────────────────────────────────────
def test_contract_reads_and_checks_the_file_field():
    contract = _contract("http://x")
    assert output_problems(contract) == []
    assert parse_outputs(contract)[0].file_field == "result.url"
    both = {**contract, "outputs": [{**contract["outputs"][0], "stream": "s"}]}
    assert "both on a stream and in a linked file" in output_problems(both)[0]
    bad = {**contract, "outputs": [{**contract["outputs"][0], "file_field": 3}]}
    assert "must be a name" in output_problems(bad)[0]


def test_the_turtle_says_which_response_field_holds_the_link():
    ttl = requirements_ttl("AreaProfile", "AreaProfile", [("Area", ["Fraction"])], [],
                           base="https://x/", outputs=parse_outputs(_contract("http://x")))
    assert 'hasResultFileField "result.url"' in ttl


def test_each_file_is_kept_with_its_instance_before_the_next_run_overwrites_it(service):
    contract = _contract(service)
    payload = {"scenario_data": {"fraction": 0.2, "area_block": [{"area": "A"}, {"area": "B"}]}}
    tr = submit_via_connection(payload, contract["connection"])
    kept = {}
    entries = fetch_result_files(contract, tr.response_data, tr.success, _saver(kept))
    assert [(e["component"], e["instance"], e["saved"], e["rows"], e["missing_columns"]) for e in entries] == [
        ("Area", "A", "results/1_profile_A.csv", 3, []), ("Area", "B", "results/2_profile_B.csv", 3, [])]
    assert entries[0]["columns"] == ["timestamp", "demand_kwh", "pv_kwh"]
    assert entries[0]["source"] == f"{service}/files/profile_A.csv"

    # The same area again at another fraction: the service overwrites, the run keeps its own.
    tr2 = submit_via_connection({"scenario_data": {"fraction": 0.9, "area_block": [{"area": "A"}]}},
                                contract["connection"])
    later = {}
    fetch_result_files(contract, tr2.response_data, tr2.success, _saver(later))
    assert b"fraction 0.2" in kept["1_profile_A.csv"] and b"fraction 0.9" in later["1_profile_A.csv"]


def test_without_identified_by_a_file_belongs_to_the_uri_the_call_sent(service):
    contract = _contract(service)
    del contract["outputs"][0]["identified_by"]
    tr = submit_via_connection({"area_block": [{"area": "A", "uri": "https://x/Area/A"}]}, contract["connection"])
    assert fetch_result_files(contract, tr.response_data, tr.success, _saver({}))[0]["instance"] == "https://x/Area/A"
    contract["outputs"][0]["component"] = "Scenario"
    assert "instance" not in fetch_result_files(contract, tr.response_data, tr.success, _saver({}))[0]


def test_columns_the_contract_declares_and_the_file_lacks_are_named(service):
    contract = _contract(service)
    contract["outputs"][0]["attributes"]["wind_kwh"] = "Area.Wind"
    tr = submit_via_connection({"area_block": [{"area": "A"}]}, contract["connection"])
    entry = fetch_result_files(contract, tr.response_data, tr.success, _saver({}))[0]
    assert entry["missing_columns"] == ["wind_kwh"]


def test_a_lost_file_or_link_is_an_error_in_its_entry_and_failed_calls_have_none(service):
    contract = _contract(service)
    gone = {"calls": [{"request": {"area": "A"}, "url": f"{service}/simulate/A",
                       "response": {"area": "A", "result": {"url": "/files/nothing.csv"}}}]}
    entry = fetch_result_files(contract, gone, True, _saver({}))[0]
    assert "status 404" in entry["error"] and entry["instance"] == "A" and "saved" not in entry

    no_link = {"calls": [{"request": {"area": "A"}, "response": {"status": "success"}}]}
    assert "no link in `result.url`" in fetch_result_files(contract, no_link, True, _saver({}))[0]["error"]

    failed = {"calls": [{"request": {"area": "A"}, "response": {}, "error": "status 500"}]}
    assert fetch_result_files(contract, failed, False, _saver({})) == []


def test_a_post_response_can_link_a_file_too_and_a_base_url_can_serve_it(service):
    contract = _contract("http://not-used.invalid", file_base_url=service, method="POST")
    _Service.files["profile_A.csv"] = CSV
    response = {"area": "A", "result": {"url": "/files/profile_A.csv"}}
    entry = fetch_result_files(contract, response, True, _saver({}))[0]
    assert entry["source"] == f"{service}/files/profile_A.csv" and entry["rows"] == 2
    assert fetch_result_files(contract, response, False, _saver({})) == []


def test_credentials_go_only_to_the_services_own_host(service):
    contract = _contract(service, auth_type="bearer", auth_credentials={"token": "secret"})
    _Service.files["profile_A.csv"] = CSV
    fetch_result_files(contract, {"result": {"url": "/files/profile_A.csv"}}, True, _saver({}))
    assert _Service.seen[-1][2].get("Authorization") == "Bearer secret"

    elsewhere = _contract("http://other.invalid", auth_type="bearer", auth_credentials={"token": "secret"},
                          method="POST")
    fetch_result_files(elsewhere, {"result": {"url": f"{service}/files/profile_A.csv"}}, True, _saver({}))
    assert "Authorization" not in _Service.seen[-1][2]


def test_a_contract_without_a_file_field_fetches_nothing(service):
    contract = _contract(service)
    del contract["outputs"][0]["file_field"]
    assert fetch_result_files(contract, {"result": {"url": "/files/x.csv"}}, True, _saver({})) == []
    assert _Service.seen == []


# ── through the API routes ───────────────────────────────────────────────────
@pytest.mark.api
def test_submit_keeps_the_files_and_serves_them(service, tmp_path, monkeypatch, api_app, api_client):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx
    from backend.workspace import WorkspaceStorage

    root = tmp_path / "testws"
    (root / "services").mkdir(parents=True)
    (root / "services" / "Svc.yaml").write_text(yaml.safe_dump(_contract(service)), encoding="utf-8")

    class Ctx:
        id = name = graphdb_repository = "testws"
        description = ""
        storage = WorkspaceStorage.local(str(root))

    api_app.dependency_overrides[get_ctx] = lambda: Ctx()
    base = "/api/workspaces/testws/submission"
    got = api_client.post(f"{base}/submit", json={
        "template_file": "Svc.yaml", "scenario_file": "s1.ttl",
        "payload": {"service_name": "x", "scenario_data": {"fraction": 0.5, "area_block": [{"area": "A"}]}}}).json()
    assert got["ok"] is True
    entry = got["result_files"][0]
    assert entry["instance"] == "A" and entry["saved"].startswith("results/AreaProfile/s1_")
    assert entry["saved"].endswith("_files/1_profile_A.csv")

    record = api_client.get(f"{base}/results/content", params={"file": got["saved"]}).json()
    assert record["result_files"] == got["result_files"]
    assert record["response"]["calls"][0]["request"] == {"fraction": 0.5, "area": "A"}
    # Kept files stay out of the list of runs, and can be downloaded.
    assert len(api_client.get(f"{base}/results").json()) == 1
    served = api_client.get(f"{base}/results/file", params={"file": entry["saved"]})
    assert served.status_code == 200 and served.content.startswith(b"timestamp,demand_kwh")
    assert api_client.get(f"{base}/results/file", params={"file": "services/Svc.yaml"}).status_code == 404
    assert api_client.get(f"{base}/results/file",
                          params={"file": "results/../services/Svc.yaml"}).status_code == 404
