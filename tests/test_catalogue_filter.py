# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The catalogue/reference-instance filter seam.

Every instance stays in the replica (catalogue entries included — the
2026-08-26 ruling); hiding them is a VIEW-time filter. These tests pin the two
halves the React explorer depends on: the semantic definition of "catalogue
instance" in the SPARQL layer, and the ``catalogue``/``has_catalogue`` fields
of ``GET /components/{name}``.
"""
from __future__ import annotations

import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi")

pytestmark = pytest.mark.api


# ── the SPARQL layer's definition of a catalogue instance ─────────────────────

def test_catalogue_query_reads_marker_and_link():
    """Either signal suffices: the explicit isCatalogueEntry marker (covers
    unused entries) or being a derivedFromCatalogue object (covers graphs built
    before the marker). Resolution is semantic — by the type's label — never by
    string-matching instance URIs."""
    captured = {}

    class _Client:
        def sparql_api_query(self, query, **kw):
            captured["q"] = query
            return pd.DataFrame({"instance": ["https://x/WindTurbine/SpecA"]})

    from backend.graphdb import queries as q
    df = q.get_catalogue_instances(_Client(), "Wind Turbine")
    text = captured["q"]
    assert "isCatalogueEntry" in text
    assert "derivedFromCatalogue" in text
    assert "UNION" in text
    assert 'rdfs:label "Wind Turbine"' in text
    assert list(df["instance"]) == ["https://x/WindTurbine/SpecA"]


def test_catalogue_uris_degrade_to_empty_on_failure(monkeypatch):
    """The filter is a convenience — a store that errors must not break the
    explorer table."""
    from backend.explorer import instances as inst
    monkeypatch.setattr(inst.gdb_queries, "get_catalogue_instances",
                        lambda c, l: (_ for _ in ()).throw(RuntimeError("down")))
    assert inst.get_catalogue_instance_uris(object(), "Wind Turbine") == set()


# ── the HTTP contract of GET /components/{name} ───────────────────────────────

@pytest.fixture()
def ws(tmp_path, monkeypatch, api_app):
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx
    from backend.workspace import WorkspaceStorage

    class _Ctx:
        id = "testws"
        name = "Test Workspace"
        graphdb_repository = "testws"
        description = ""

    root = tmp_path / _Ctx.id
    root.mkdir()
    ctx = _Ctx()
    ctx.storage = WorkspaceStorage.local(str(root))
    api_app.dependency_overrides[get_ctx] = lambda: ctx
    return root


def test_component_table_flags_catalogue_rows(api_client, ws, monkeypatch):
    import backend.explorer as bx
    import apps.api.explorer as route_mod

    uri_sited = "https://digicities.info/proj/testws/WindTurbine/T1"
    uri_cat = "https://digicities.info/proj/testws/WindTurbine/SpecA"
    df = pd.DataFrame([
        {"instance_id": "T1", "URI": uri_sited, "label": "T1"},
        {"instance_id": "SpecA", "URI": uri_cat, "label": "SpecA"},
    ])

    monkeypatch.setattr(route_mod, "graph_client", lambda ctx: object())
    monkeypatch.setattr(bx, "get_component_data_unified",
                        lambda c, n: ([{"instance": {"value": uri_sited}}], []))
    monkeypatch.setattr(bx, "process_enhanced_component_data", lambda i, a: df)
    monkeypatch.setattr(bx, "get_component_sources", lambda c, n: pd.DataFrame())
    monkeypatch.setattr(bx, "attach_sources", lambda d, s: d)
    monkeypatch.setattr(bx, "get_visible_columns", lambda d: ["instance_id", "label"])
    monkeypatch.setattr(bx, "curve_columns", lambda d: [])
    monkeypatch.setattr(bx, "get_catalogue_instance_uris", lambda c, n: {uri_cat})

    body = api_client.get("/api/workspaces/testws/components/Wind%20Turbine").json()
    assert body["catalogue"] == ["SpecA"]
    assert body["has_catalogue"] is True
    assert [r["instance_id"] for r in body["rows"]] == ["T1", "SpecA"]


def test_component_table_empty_carries_catalogue_fields(api_client, ws, monkeypatch):
    import backend.explorer as bx
    import apps.api.explorer as route_mod

    monkeypatch.setattr(route_mod, "graph_client", lambda ctx: object())
    monkeypatch.setattr(bx, "get_component_data_unified", lambda c, n: ([], []))
    body = api_client.get("/api/workspaces/testws/components/Nothing").json()
    assert body["catalogue"] == []
    assert body["has_catalogue"] is False
