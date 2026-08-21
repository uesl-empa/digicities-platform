# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Unit tests for ``backend.graphdb.client.UnifiedGraphDBClient``.

Every SPARQL call in the platform flows through this client, so these tests
pin the parts the app actually leans on: which auth mode the constructor
picks, how endpoint URLs are built for query/update/graph-store operations on
both triplestore backends (Fuseki vs GraphDB), how a SPARQL-JSON response is
parsed into a DataFrame/dict, and what happens on auth errors, server errors
and malformed JSON. All HTTP is mocked at the ``requests`` seam — no network.
"""
from __future__ import annotations

import json
import urllib.parse

import pytest

pytest.importorskip("rdflib")
requests = pytest.importorskip("requests")

from backend.graphdb.client import UnifiedGraphDBClient  # noqa: E402
from backend.triplestore.factory import get_backend  # noqa: E402


# A canned SPARQL 1.1 JSON results document, as Fuseki/GraphDB return it.
SPARQL_JSON = {
    "head": {"vars": ["s", "n"]},
    "results": {"bindings": [
        {"s": {"type": "uri", "value": "http://x/a"},
         "n": {"type": "literal", "value": "1"}},
        # second row has no binding for ?n — must become None, not crash
        {"s": {"type": "uri", "value": "http://x/b"}},
    ]},
}


class FakeResponse:
    """Just enough of ``requests.Response`` for the client's code paths."""

    def __init__(self, status_code=200, json_data=None, headers=None,
                 text="", bad_json=False):
        self.status_code = status_code
        self._json = json_data
        self._bad_json = bad_json
        self.headers = headers or {}
        self.text = text
        self.content = text.encode()

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._bad_json:
            raise json.JSONDecodeError("bad", "doc", 0)
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture()
def backend_env(monkeypatch):
    """Pin the triplestore backend selection and base URL for the test.

    ``get_backend`` is an lru_cache singleton, so the cache is cleared before
    and after — otherwise a backend built under this test's env leaks into
    the rest of the suite (and vice versa).
    """
    def _use(name: str):
        monkeypatch.setenv("TRIPLESTORE_BACKEND", name)
        monkeypatch.setenv("GRAPHDB_URL", "http://ts:7200")
        monkeypatch.delenv("FUSEKI_URL", raising=False)
        get_backend.cache_clear()

    get_backend.cache_clear()
    yield _use
    get_backend.cache_clear()


def _no_auth_client(**kw):
    return UnifiedGraphDBClient(token="local", selected_repo="ws1", **kw)


# ── constructor / auth-mode selection ────────────────────────────────────────
def test_no_auth_mode_via_local_token():
    client = _no_auth_client(base_url="http://ts:7200")
    assert client.auth_mode == "no_auth"
    assert client.access_token is None
    assert client.repository == "ws1"
    assert client.base_url == "http://ts:7200"
    # no Authorization header on the session in no-auth mode
    assert "Authorization" not in client.session.headers


def test_no_auth_mode_empty_token_defaults_repo():
    client = UnifiedGraphDBClient(token="", base_url="http://ts:7200")
    assert client.auth_mode == "no_auth"
    assert client.repository == "digicities"


def test_token_mode_sets_bearer_header():
    client = UnifiedGraphDBClient(token="abc123", selected_repo="ws1",
                                  base_url="http://ts:7200")
    assert client.auth_mode == "token"
    assert client.access_token == "Bearer abc123"
    assert client.session.headers["Authorization"] == "Bearer abc123"


def test_credentials_mode_uses_graphdb_rest_login(monkeypatch):
    """Without KEYCLOAK_TOKEN_URL, credentials go to /rest/login/{user} and the
    Authorization response header becomes the token verbatim."""
    monkeypatch.delenv("KEYCLOAK_TOKEN_URL", raising=False)
    monkeypatch.setenv("GRAPHDB_URL", "http://ts:7200")
    seen = {}

    def fake_request(method, url, headers=None, **kw):
        seen["method"], seen["url"], seen["headers"] = method, url, headers
        return FakeResponse(200, headers={"Authorization": "GDB tok-1"})

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    client = UnifiedGraphDBClient(username="u", password="pw", repository="repo1")
    assert client.auth_mode == "credentials"
    assert seen["url"] == "http://ts:7200/rest/login/u"
    assert seen["headers"]["X-GraphDB-Password"] == "pw"
    assert client.access_token == "GDB tok-1"


def test_credentials_mode_uses_keycloak_when_configured(monkeypatch):
    """With KEYCLOAK_TOKEN_URL set, a password grant is exchanged for a bearer."""
    monkeypatch.setenv("KEYCLOAK_TOKEN_URL", "http://kc/token")
    monkeypatch.setenv("GRAPHDB_URL", "http://ts:7200")
    seen = {}

    def fake_request(method, url, headers=None, data=None, **kw):
        seen["url"], seen["data"] = url, data
        return FakeResponse(200, json_data={"access_token": "kc-tok"})

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    client = UnifiedGraphDBClient(username="u", password="pw", repository="repo1")
    assert seen["url"] == "http://kc/token"
    assert "grant_type=password" in seen["data"]
    assert client.access_token == "Bearer kc-tok"


def test_constructor_rejects_incomplete_args():
    with pytest.raises(ValueError, match="must be provided"):
        UnifiedGraphDBClient(username="u", password="pw")  # no repository


# ── endpoint URL building (Fuseki vs GraphDB) ────────────────────────────────
def test_query_and_update_urls_fuseki(backend_env):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    q = "SELECT * WHERE { ?s ?p ?o }"
    assert client._query_url(q) == (
        f"http://ts:7200/ws1/query?query={urllib.parse.quote(q)}")
    assert client._update_url("INSERT DATA {}").startswith(
        "http://ts:7200/ws1/update?update=")


def test_query_and_update_urls_graphdb(backend_env):
    backend_env("graphdb")
    client = _no_auth_client(base_url="http://ts:7200")
    q = "SELECT * WHERE { ?s ?p ?o }"
    assert client._query_url(q) == (
        f"http://ts:7200/repositories/ws1?query={urllib.parse.quote(q)}")
    assert client._update_url("INSERT DATA {}").startswith(
        "http://ts:7200/repositories/ws1/statements?update=")


def test_graph_store_url_named_graph_per_backend(backend_env):
    graph = "http://scenarios/demo"
    quoted = urllib.parse.quote(graph, safe="")

    backend_env("fuseki")
    fus = _no_auth_client(base_url="http://ts:7200")
    assert fus._graph_store_url(urllib.parse.quote(graph)) == (
        f"http://ts:7200/ws1/data?graph={quoted}")

    backend_env("graphdb")
    gdb = _no_auth_client(base_url="http://ts:7200")
    assert gdb._graph_store_url(urllib.parse.quote(graph)) == (
        f"http://ts:7200/repositories/ws1/rdf-graphs/service?graph={quoted}")


def test_graph_store_url_strips_angle_brackets(backend_env):
    """SPARQL-style ``<iri>`` graph names must lose the brackets — the Graph
    Store Protocol wants the bare IRI or the server rejects it with 400."""
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    url = client._graph_store_url("<http://scenarios/demo>")
    assert url == ("http://ts:7200/ws1/data?graph="
                   + urllib.parse.quote("http://scenarios/demo", safe=""))


def test_graph_store_url_default_graph_per_backend(backend_env):
    backend_env("fuseki")
    assert _no_auth_client(base_url="http://ts:7200")._graph_store_url(None) \
        == "http://ts:7200/ws1/data?default"
    backend_env("graphdb")
    assert _no_auth_client(base_url="http://ts:7200")._graph_store_url(None) \
        == "http://ts:7200/repositories/ws1/statements"


# ── sparql_api_query: response parsing ───────────────────────────────────────
def test_sparql_api_query_parses_df(backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(200, json_data=SPARQL_JSON))

    df = client.sparql_api_query("SELECT * WHERE { ?s ?p ?o }")
    assert list(df.columns) == ["s", "n"]
    assert df["s"].tolist() == ["http://x/a", "http://x/b"]
    assert df["n"].tolist()[0] == "1"
    import pandas as pd
    assert pd.isna(df["n"].tolist()[1])  # unbound variable → missing, not a crash


def test_sparql_api_query_dict_and_response_formats(backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    one_row = {"head": {"vars": ["flag"]},
               "results": {"bindings": [
                   {"flag": {"type": "literal", "value": "true",
                             "datatype": "http://www.w3.org/2001/XMLSchema#boolean"}}]}}
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(200, json_data=one_row))

    as_dict = client.sparql_api_query("ASK-ish", out_format="dict")
    assert as_dict == {"flag": True}  # xsd:boolean coerced to Python bool

    as_resp = client.sparql_api_query("q", out_format="response")
    assert as_resp.status_code == 200


def test_sparql_api_query_sends_infer_flag_and_auth_header(backend_env, monkeypatch):
    backend_env("fuseki")
    monkeypatch.setenv("GRAPHDB_URL", "http://ts:7200")
    client = UnifiedGraphDBClient(token="tok", selected_repo="ws1",
                                  base_url="http://ts:7200")
    seen = {}

    def fake_request(method, url, headers=None, **kw):
        seen["method"], seen["url"], seen["headers"] = method, url, headers
        return FakeResponse(200, json_data=SPARQL_JSON)

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    client.sparql_api_query("SELECT 1", infer=False)
    assert seen["method"] == "GET"
    assert seen["url"].endswith("&infer=False")
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_sparql_api_query_rejects_bad_out_format(backend_env):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    with pytest.raises(ValueError, match="out_format"):
        client.sparql_api_query("q", out_format="xml")


# ── sparql_api_query: error handling ─────────────────────────────────────────
def test_sparql_api_query_client_error_returns_none_and_fires_hook(
        backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    client.retry_delay = 0
    errors = []
    monkeypatch.setattr(client, "_on_query_error",
                        lambda msg, query: errors.append((msg, query)))
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(400, text="parse error"))

    assert client.sparql_api_query("broken query") is None
    assert len(errors) == 1
    assert errors[0][1] == "broken query"


def test_sparql_api_query_retries_server_errors_then_gives_up(
        backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200", max_retries=2)
    client.retry_delay = 0
    calls = []

    def fake_request(*a, **k):
        calls.append(1)
        return FakeResponse(503)

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    assert client.sparql_api_query("q") is None
    assert len(calls) == 3  # initial attempt + 2 retries


def test_sparql_api_query_malformed_json_returns_none(backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200", max_retries=0)
    client.retry_delay = 0
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(200, bad_json=True, text="<html>"))
    assert client.sparql_api_query("q") is None


def test_sparql_api_query_auth_error_refreshes_token_and_retries(
        backend_env, monkeypatch):
    """A 401 in token mode triggers the token_refresher once, then the retried
    request carries the fresh bearer and succeeds."""
    backend_env("fuseki")
    client = UnifiedGraphDBClient(token="stale", selected_repo="ws1",
                                  base_url="http://ts:7200",
                                  token_refresher=lambda: "fresh")
    client.retry_delay = 0
    headers_seen = []

    def fake_request(method, url, headers=None, **kw):
        headers_seen.append(headers.get("Authorization"))
        if len(headers_seen) == 1:
            return FakeResponse(401)
        return FakeResponse(200, json_data=SPARQL_JSON)

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    df = client.sparql_api_query("q")
    assert df is not None
    assert headers_seen == ["Bearer stale", "Bearer fresh"]


def test_sparql_api_query_auth_error_without_refresher_fails(
        backend_env, monkeypatch):
    backend_env("fuseki")
    client = UnifiedGraphDBClient(token="stale", selected_repo="ws1",
                                  base_url="http://ts:7200")
    client.retry_delay = 0
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(401))
    assert client.sparql_api_query("q") is None


def test_execute_query_returns_raw_bindings(backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    monkeypatch.setattr(
        "backend.graphdb.client.requests.request",
        lambda *a, **k: FakeResponse(200, json_data=SPARQL_JSON))
    bindings = client.execute_query("q")
    assert bindings == SPARQL_JSON["results"]["bindings"]


# ── writes: sparql_update + upload_ttl ───────────────────────────────────────
def test_sparql_update_posts_form_encoded_body(backend_env, monkeypatch):
    """The update must travel in the request body (``update=<stmt>``) — the
    URL-parameter form is silently ignored by Fuseki/GraphDB."""
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    seen = {}

    def fake_post(url, headers=None, data=None, auth=None, **kw):
        seen.update(url=url, data=data, auth=auth)
        return FakeResponse(200)

    monkeypatch.setattr("backend.graphdb.client.requests.post", fake_post)
    client.sparql_update("INSERT DATA { <urn:a> <urn:b> <urn:c> }")
    assert seen["url"] == "http://ts:7200/ws1/update"
    assert seen["data"] == {"update": "INSERT DATA { <urn:a> <urn:b> <urn:c> }"}


def test_upload_ttl_posts_turtle_to_named_graph(backend_env, monkeypatch):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    seen = {}

    def fake_request(method, url, headers=None, data=None, **kw):
        seen.update(method=method, url=url, headers=headers)
        return FakeResponse(200)

    monkeypatch.setattr("backend.graphdb.client.requests.request", fake_request)
    ttl = "<urn:a> <urn:b> <urn:c> ."
    client.upload_ttl(ttl_str=ttl, graph_name="http://g/1")
    assert seen["method"] == "POST"
    assert seen["url"] == ("http://ts:7200/ws1/data?graph="
                           + urllib.parse.quote("http://g/1", safe=""))
    assert seen["headers"]["Content-Type"] == "text/turtle"

    # replace_existing switches the verb to PUT
    client.upload_ttl(ttl_str=ttl, graph_name="http://g/1", replace_existing=True)
    assert seen["method"] == "PUT"


def test_upload_ttl_requires_exactly_one_source(backend_env):
    backend_env("fuseki")
    client = _no_auth_client(base_url="http://ts:7200")
    with pytest.raises(ValueError, match="One and only one"):
        client.upload_ttl()
    with pytest.raises(ValueError, match="One and only one"):
        client.upload_ttl(ttl_str="x", ttl_file_path="y.ttl")
