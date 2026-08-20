# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Phase-5 backend moves: the Replica Builder's editor logic, headless.

The flagship is the round trip: ReplicaDraft → 6-row-header workbook →
``process_excel_to_ttl`` (the ONE workbook parser) → TTL → backend
graph_loader parse-back → the same model. Around it: the instance-URI rules,
instance/link CRUD on plain lists, the attribute rules distilled out of the
form widgets, the TTL generators with explicit model args, draft dict round
trips, and the shim-identity guarantees (old import paths hand back the
backend objects).
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from rdflib import Graph, Literal, Namespace, URIRef  # noqa: E402

from backend.replica_builder import attribute_rules as rules  # noqa: E402
from backend.replica_builder import model as model  # noqa: E402
from backend.replica_builder import ttl as bttl  # noqa: E402
from backend.replica_builder.draft import ReplicaDraft, build_workbook  # noqa: E402
from backend.replica_builder.excel_import import (  # noqa: E402
    import_workbook,
    parse_generated_ttl,
)
from backend.replica_builder.model import ComponentInstance  # noqa: E402

DICI = Namespace("https://digicities.info/ontology#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
PROJ = "https://x.org/p"


# ---------------------------------------------------------------------------
# The flagship: draft -> workbook -> process_excel_to_ttl -> parse-back
# ---------------------------------------------------------------------------

def _flagship_draft() -> ReplicaDraft:
    return ReplicaDraft.from_request([
        {"cls": "WindPark",
         "columns": [{"name": "label", "type": "Annotation"}],
         "rows": [{"id": "ParkA", "label": "Park A"}]},
        {"cls": "WindTurbine",
         "columns": [
             {"name": "HubHeight", "type": "Physical", "unit": "M"},
             {"name": "TurbineType", "type": "Categorical"},
             {"name": "partOf", "type": "ClassObject", "predicate": "partOf"},
         ],
         "rows": [
             {"id": "T1", "HubHeight": 120, "TurbineType": "Onshore",
              "partOf": "WindPark/ParkA"},
             {"id": "T2", "HubHeight": 95.5, "TurbineType": "Offshore",
              "partOf": "WindPark/ParkA"},
         ]},
    ])


def test_draft_workbook_ttl_roundtrip(tmp_path):
    draft = _flagship_draft()
    xlsx = tmp_path / "replica.xlsx"
    build_workbook(draft, xlsx)

    ttl, instances = import_workbook(str(xlsx), PROJ, uri_mode="default")

    # The TTL itself is valid Turtle.
    g = Graph()
    g.parse(data=ttl, format="turtle")
    assert len(g) > 0

    by_id = {inst.id: inst for inst in instances}
    assert set(by_id) == {"ParkA", "T1", "T2"}

    park = by_id["ParkA"]
    assert park.component_type == "WindPark"
    assert park.uri == f"{PROJ}/WindPark/ParkA"
    assert park.label == "Park A"

    t1 = by_id["T1"]
    assert t1.component_type == "WindTurbine"
    assert t1.uri == f"{PROJ}/WindTurbine/T1"
    # Physical attribute: value + unit recovered.
    hub = t1.attributes["HubHeight"]
    assert hub["type"] == "Physical"
    assert float(hub["value"]) == 120.0
    assert hub["unit"] == "M"
    # Categorical attribute: category value recovered.
    assert t1.attributes["TurbineType"]["category_value"] == "Onshore"
    # ClassObject link column: direct predicate to the sibling instance.
    assert t1.class_objects == {"partOf": f"{PROJ}/WindPark/ParkA"}

    t2 = by_id["T2"]
    assert float(t2.attributes["HubHeight"]["value"]) == 95.5
    assert t2.attributes["TurbineType"]["category_value"] == "Offshore"

    # And back to a draft: the recovered model re-expresses the input schema.
    round_draft = ReplicaDraft.from_instances(instances, project_uri=PROJ)
    by_cls = {c.cls: c for c in round_draft.components}
    assert set(by_cls) == {"WindPark", "WindTurbine"}
    wt = by_cls["WindTurbine"]
    row_t1 = next(r for r in wt.rows if r["id"] == "T1")
    assert float(row_t1["HubHeight"]) == 120.0
    assert row_t1["TurbineType"] == "Onshore"
    assert row_t1["partOf"] == "WindPark/ParkA"     # relativized back to Sheet/id
    cols = {c.name: c for c in wt.columns}
    assert cols["HubHeight"].type == "Physical" and cols["HubHeight"].unit == "M"
    assert cols["partOf"].type == "ClassObject" and cols["partOf"].predicate == "partOf"


def test_timeseries_columns_roundtrip(tmp_path):
    """A session Physical attribute with a static value AND a historic
    reference maps onto two same-named workbook columns (via the draft's
    per-column row key) and both survive the TTL round trip."""
    inst = ComponentInstance(
        id="B1", component_type="Building",
        uri=f"{PROJ}/Building/B1", label="B1",
        attributes={"Power": {"type": "Physical", "value": 5.0, "unit": "KiloW",
                              "historic_reference": "power.csv"}},
    )
    draft = ReplicaDraft.from_instances([inst], project_uri=PROJ)
    (comp,) = draft.components
    names = [c.name for c in comp.columns]
    assert names.count("Power") == 2                    # value + Historic variant
    assert {c.type for c in comp.columns} == {"Physical", "Historic"}

    xlsx = tmp_path / "b.xlsx"
    build_workbook(draft, xlsx)
    _, instances = import_workbook(str(xlsx), PROJ, uri_mode="default")
    (back,) = instances
    power = back.attributes["Power"]
    assert power["type"] in ("Physical", "Dynamic")
    assert float(power["value"]) == 5.0
    assert power["unit"] == "KiloW"
    assert power["historic_reference"] == "power.csv"


def test_local_parse_recovers_annotations_and_references(tmp_path):
    """Free-form Annotation columns (project namespace) and rdfs comments come
    back as annotations; Reference/TimeSeries nodes never become instances."""
    draft = ReplicaDraft.from_request([
        {"cls": "Building",
         "columns": [{"name": "comment", "type": "Annotation"},
                     {"name": "BaseCarrier", "type": "Annotation"}],
         "rows": [{"id": "B1", "comment": "a note", "BaseCarrier": "Gas"}]},
    ])
    xlsx = tmp_path / "a.xlsx"
    build_workbook(draft, xlsx)
    _, instances = import_workbook(str(xlsx), PROJ, uri_mode="default")
    (b1,) = instances
    assert b1.annotations["comment"] == "a note"
    assert b1.annotations["BaseCarrier"] == "Gas"       # :BaseCarrier "Gas"


# ---------------------------------------------------------------------------
# model.py: URI rules + instance/link CRUD on plain lists
# ---------------------------------------------------------------------------

def test_generate_instance_uri_modes():
    assert model.generate_instance_uri(PROJ, "Building", "B1", "default") \
        == f"{PROJ}/Building/B1"
    assert model.generate_instance_uri(PROJ, "Building", "B1", "complete-project-uri") \
        == f"{PROJ}#B1"
    assert model.generate_instance_uri(PROJ, "Building", "B1", "full-uri-in-cell") \
        == f"{PROJ}/B1"
    # Unknown mode falls back to default.
    assert model.generate_instance_uri(PROJ, "Building", "B1", "???") \
        == f"{PROJ}/Building/B1"


def test_create_and_delete_instance():
    instances, links = [], []
    inst = model.create_instance(instances, "Building", "B1", PROJ, "default", "House")
    assert inst.uri == f"{PROJ}/Building/B1" and inst.label == "House"
    assert instances == [inst]

    with pytest.raises(ValueError, match="already exists"):
        model.create_instance(instances, "Building", "B1", PROJ, "default")

    model.create_instance(instances, "PV", "P1", PROJ, "default")
    link, err = model.create_link(instances, links, "B1", "P1", "locatedIn")
    assert err is None and links == [link]

    new_instances, new_links, deleted = model.delete_instance(instances, links, "B1")
    assert deleted
    assert [i.id for i in new_instances] == ["P1"]
    assert new_links == []                              # cascade removed the link

    # Deleting a missing id: nothing changes, deleted=False.
    same_instances, same_links, deleted = model.delete_instance(new_instances, new_links, "nope")
    assert not deleted and [i.id for i in same_instances] == ["P1"]


def test_create_link_outcomes():
    instances, links = [], []
    model.create_instance(instances, "Building", "B1", PROJ, "default")
    model.create_instance(instances, "PV", "P1", PROJ, "default")

    link, err = model.create_link(instances, links, "B1", "P1", "locatedIn")
    assert err is None
    assert link["source_uri"] == f"{PROJ}/Building/B1"
    assert link["target_uri"] == f"{PROJ}/PV/P1"
    assert link["property"] == "locatedIn"

    # Custom property wins over the ontology pick.
    link2, err = model.create_link(instances, links, "P1", "B1", "locatedIn", "feeds")
    assert err is None and link2["property"] == "feeds"

    assert model.create_link(instances, links, "B1", "P1", "locatedIn") == (None, "duplicate")
    assert model.create_link(instances, links, "B1", "nope", "locatedIn") == (None, "not_found")

    remaining, deleted = model.delete_link(links, "B1", "P1", "locatedIn")
    assert deleted and [l["property"] for l in remaining] == ["feeds"]
    _, deleted = model.delete_link(remaining, "B1", "P1", "locatedIn")
    assert not deleted

    assert model.get_links_for_instance(links, "B1") == links
    assert model.get_links_for_instance(links, "nope") == []


def test_component_type_names_filters_attribute_classes():
    comps = {"Building": 1, "BuildingAttribute": 2, "Attribute": 3,
             "Component": 4, "PV": 5}
    assert model.component_type_names(comps) == ["Building", "PV"]


def test_extract_link_property_names():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"property": [
        "https://digicities.info/ontology#locatedIn",
        "https://digicities.info/ontology#connectedTo",
        "https://digicities.info/ontology#locatedIn",   # duplicate collapses
        "plainName",
    ], "label": [None, None, None, None]})
    assert model.extract_link_property_names(df) == \
        ["connectedTo", "locatedIn", "plainName"]
    assert model.extract_link_property_names(None) == []
    assert model.load_link_properties(None) == model.DEFAULT_LINK_PROPERTIES


# ---------------------------------------------------------------------------
# attribute_rules.py: the rules distilled out of the form widgets
# ---------------------------------------------------------------------------

class _Constraints:
    def __init__(self, **kw):
        self.attribute_type = kw.get("attribute_type", "Physical")
        self.default_unit = kw.get("default_unit")
        self.ratio_numerator_unit = kw.get("ratio_numerator_unit")
        self.ratio_denominator_unit = kw.get("ratio_denominator_unit")


def test_unit_options_add_mode_preselects_ontology_default():
    options, idx = rules.unit_options(["KiloW", "M", "W"], default_unit="M")
    assert options == ["KiloW", "M", "W"] and options[idx] == "M"
    # Default missing from the list: inserted at the front.
    options, idx = rules.unit_options(["KiloW", "W"], default_unit="M2")
    assert options[0] == "M2" and idx == 0
    # No units loaded at all: the ontology default is the only option.
    options, idx = rules.unit_options(None, default_unit="M")
    assert options == ["M"] and idx == 0


def test_unit_options_edit_mode_preselects_current_unit():
    options, idx = rules.unit_options(["KiloW", "M", "W"], default_unit="M",
                                      current_unit="W")
    assert options[idx] == "W"
    # Stored unit not in the loaded list: inserted and preselected.
    options, idx = rules.unit_options(["KiloW", "M"], current_unit="FT")
    assert options[0] == "FT" and idx == 0
    # No stored unit yet ('' in the edit forms): first option, as before.
    options, idx = rules.unit_options(["KiloW", "M"], default_unit="M",
                                      current_unit="")
    assert idx == 0


def test_unit_options_does_not_mutate_session_list():
    session_units = ["KiloW", "W"]
    rules.unit_options(session_units, default_unit="M", current_unit="FT")
    assert session_units == ["KiloW", "W"]


def test_ratio_unit_split_and_compose():
    assert rules.split_ratio_unit("KiloW-HR/M2") == ("KiloW-HR", "M2")
    assert rules.compose_ratio_unit("KiloW-HR", "M2") == "KiloW-HR/M2"
    c = _Constraints(ratio_numerator_unit="W", ratio_denominator_unit="M2")
    assert rules.split_ratio_unit("", c) == ("W", "M2")
    assert rules.split_ratio_unit("KiloW-HR/M2", c) == ("KiloW-HR", "M2")


def test_looks_like_file_reference():
    assert rules.looks_like_file_reference("demand.csv")
    assert rules.looks_like_file_reference("dir/file")
    assert not rules.looks_like_file_reference("Residential")
    assert not rules.looks_like_file_reference("")
    assert not rules.looks_like_file_reference(None)


def test_default_attribute_type():
    assert rules.default_attribute_type(None) == "Physical"
    assert rules.default_attribute_type(_Constraints(attribute_type="Event")) == "Event"


def test_validate_attribute_config():
    assert rules.validate_attribute_config("Physical", {"value": 1.0, "unit": "M"}) == []
    assert rules.validate_attribute_config("Categorical", {"category_value": "MFH"}) == []
    assert rules.validate_attribute_config("Categorical", {}) \
        == ["Categorical attribute needs a 'category_value'"]
    assert rules.validate_attribute_config(
        "Event", {"temporal_value": "2024", "temporal_precision": "Year"}) == []
    assert any("temporal precision" in p for p in rules.validate_attribute_config(
        "Event", {"temporal_value": "2024", "temporal_precision": "Century"}))
    assert any("numeric" in p for p in rules.validate_attribute_config(
        "SimpleCost", {"value": "lots", "currency": "CHF"}))
    assert any("Unknown attribute type" in p
               for p in rules.validate_attribute_config("Bogus", {}))


# ---------------------------------------------------------------------------
# ttl.py: generators against a small model, assertions via rdflib
# ---------------------------------------------------------------------------

def _small_model():
    b1 = ComponentInstance(
        id="B1", component_type="Building", uri=f"{PROJ}/Building/B1",
        label="House One",
        attributes={
            "FloorArea": {"type": "Physical", "value": 120.5, "unit": "M2"},
            "BuildingType": {"type": "Categorical", "category_value": "MFH"},
        },
        annotations={"comment": "a note"},
    )
    p1 = ComponentInstance(
        id="P1", component_type="PV", uri=f"{PROJ}/PV/P1", label="Roof PV")
    links = [{"source_id": "P1", "target_id": "B1",
              "source_uri": p1.uri, "target_uri": b1.uri,
              "source_type": "PV", "target_type": "Building",
              "property": "locatedIn",
              "source_label": "Roof PV", "target_label": "House One"}]
    return [b1, p1], links


def test_generate_classes_and_attributes_ttl():
    instances, _ = _small_model()
    ttl = bttl.generate_classes_and_attributes_ttl(instances)

    ok, err = bttl.validate_ttl(ttl)
    assert ok, err
    g = Graph()
    g.parse(data=ttl, format="turtle")

    b1 = URIRef(f"{PROJ}/Building/B1")
    attr = URIRef(f"{PROJ}/Building/B1/FloorArea")
    assert (b1, rdflib.RDF.type, DICI.Building) in g
    assert (b1, rdflib.RDFS.label, Literal("House One")) in g
    assert (b1, rdflib.RDFS.comment, Literal("a note")) in g
    assert (b1, DICI.hasAttribute, attr) in g
    # Typed per-attribute predicate alongside the generic hasAttribute.
    assert (b1, DICI.hasBuildingFloorAreaAttribute, attr) in g
    # Attribute node: kind class, decimal value, QUDT unit IRI.
    assert (attr, rdflib.RDF.type, DICI.PhysicalAttribute) in g
    values = list(g.objects(attr, QUDT.value))
    assert values and str(values[0]) == "120.5"
    assert (attr, QUDT.unit,
            URIRef("http://qudt.org/vocab/unit/M2")) in g
    # Categorical attribute dual-typed with its value class.
    cat = URIRef(f"{PROJ}/Building/B1/BuildingType")
    assert (cat, rdflib.RDF.type, DICI.CategoricalAttribute) in g
    assert (cat, rdflib.RDF.type, DICI.MFH) in g


def test_generate_system_description_ttl_and_validate():
    instances, links = _small_model()
    ttl = bttl.generate_system_description_ttl(links)
    ok, err = bttl.validate_ttl(ttl)
    assert ok, err
    g = Graph()
    g.parse(data=ttl, format="turtle")
    assert (URIRef(f"{PROJ}/PV/P1"), DICI.locatedIn,
            URIRef(f"{PROJ}/Building/B1")) in g

    ok, err = bttl.validate_ttl("this is not turtle @@@")
    assert not ok and err


def test_ttl_roundtrip_through_backend_graph_loader():
    """UI-generated TTL parses back through the same backend loader the graph
    load path uses (kind classes asserted → no ontology needed)."""
    instances, links = _small_model()
    classes_ttl = bttl.generate_classes_and_attributes_ttl(instances)
    back = parse_generated_ttl(classes_ttl)
    by_id = {inst.id: inst for inst in back}
    assert set(by_id) == {"B1", "P1"}
    fa = by_id["B1"].attributes["FloorArea"]
    assert fa["type"] == "Physical" and float(fa["value"]) == 120.5 and fa["unit"] == "M2"
    assert by_id["B1"].attributes["BuildingType"]["category_value"] == "MFH"

    from backend.replica_builder.graph_loader import parse_links_from_graph
    sys_g = Graph()
    sys_g.parse(data=bttl.generate_system_description_ttl(links), format="turtle")
    recovered = parse_links_from_graph(sys_g, back)
    assert [(l["source_id"], l["property"], l["target_id"]) for l in recovered] \
        == [("P1", "locatedIn", "B1")]


# ---------------------------------------------------------------------------
# ReplicaDraft: dict round trip + session-state constructor
# ---------------------------------------------------------------------------

def test_draft_dict_roundtrip():
    draft = _flagship_draft()
    again = ReplicaDraft.from_dict(draft.to_dict())
    assert again == draft
    assert again.to_dict() == draft.to_dict()


def test_draft_from_session_state():
    instances, _ = _small_model()
    state = {"replica_instances": instances, "replica_project_uri": PROJ}
    draft = ReplicaDraft.from_session_state(state)
    by_cls = {c.cls: c for c in draft.components}
    assert set(by_cls) == {"Building", "PV"}
    row = by_cls["Building"].rows[0]
    assert row["id"] == "B1" and row["FloorArea"] == 120.5
    assert row["BuildingType"] == "MFH" and row["comment"] == "a note"
    cols = {c.name: c.type for c in by_cls["Building"].columns}
    assert cols == {"comment": "Annotation", "FloorArea": "Physical",
                    "BuildingType": "Categorical"}


def test_draft_from_request_validates():
    with pytest.raises(ValueError, match="'cls'"):
        ReplicaDraft.from_request([{"columns": [], "rows": []}])
    with pytest.raises(ValueError, match="'name'"):
        ReplicaDraft.from_request([{"cls": "X", "columns": [{"type": "Physical"}]}])


# ---------------------------------------------------------------------------
# Shims: old import paths hand back the backend objects (Phase-4b style)
# ---------------------------------------------------------------------------

def test_replica_shim_identity():
    pytest.importorskip("streamlit")
    import components.replica_builder.replica_instance_manager as im
    import components.replica_builder.replica_link_manager as lm
    import components.replica_builder.replica_ttl_generator as tg
    import components.replica_builder.replica_graph_loader as gl
    import components.replica_builder.replica_ontology_loader as ol

    assert im.ComponentInstance is model.ComponentInstance
    assert im.generate_instance_uri is model.generate_instance_uri
    assert lm.DEFAULT_LINK_PROPERTIES is model.DEFAULT_LINK_PROPERTIES

    assert tg.validate_ttl is bttl.validate_ttl
    assert tg.generate_instance_ttl is bttl.generate_instance_ttl
    assert tg.generate_attribute_ttl is bttl.generate_attribute_ttl

    from backend.replica_builder import graph_loader as bgl
    assert gl.parse_single_attribute is bgl.parse_single_attribute
    assert gl.parse_instances_from_graph is bgl.parse_instances_from_graph
    assert gl.parse_attributes_from_graph is bgl.parse_attributes_from_graph
    assert gl.convert_to_replica_instances is bgl.convert_to_replica_instances

    from backend.replica_builder import ontology_queries as boq
    assert ol.ComponentClass is boq.ComponentClass
    assert ol.AttributeClass is boq.AttributeClass
    assert ol.extract_local_name is boq.extract_local_name
    assert ol.get_common_qudt_units is boq.get_common_qudt_units


def test_excel_importer_shim_delegates_to_backend(tmp_path):
    """The old ``parse_excel_file`` name still works but is now the backend
    converter path — same instances as calling the backend directly."""
    pytest.importorskip("streamlit")
    from components.replica_builder import replica_excel_importer as imp

    draft = _flagship_draft()
    xlsx = tmp_path / "replica.xlsx"
    build_workbook(draft, xlsx)

    got = imp.parse_excel_file(str(xlsx), PROJ, "default")
    _, expected = import_workbook(str(xlsx), PROJ, "default")
    assert got == {"instances": [inst.to_dict() for inst in expected]}


# ---------------------------------------------------------------------------
# API: /replica/model round trip (draft schema comes back)
# (the api_app fixture skips these when fastapi isn't installed)
# ---------------------------------------------------------------------------

class _Ctx:
    id = "replicaws"
    name = "Replica WS"
    graphdb_repository = "replicaws"
    description = "replica-backend test workspace"


@pytest.fixture()
def replica_ws(tmp_path, monkeypatch, api_app):
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx

    api_app.dependency_overrides[get_ctx] = lambda: _Ctx()
    root = tmp_path / _Ctx.id
    root.mkdir()
    return root


def test_api_generate_then_model_roundtrip(replica_ws, api_client):
    base = f"/api/workspaces/{_Ctx.id}/replica"
    spec = {
        "components": [
            {"cls": "Building",
             "columns": [{"name": "FloorArea", "type": "Physical", "unit": "M2"}],
             "rows": [{"id": "B1", "FloorArea": 120.5}]},
        ],
        "persist": True,
    }
    r = api_client.post(f"{base}/generate", json=spec)
    assert r.status_code == 200, r.text
    assert r.json()["ttl"]

    r = api_client.get(f"{base}/model")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file"] == f"{_Ctx.id}.ttl"
    (inst,) = body["instances"]
    assert inst["id"] == "B1" and inst["component_type"] == "Building"
    assert float(inst["attributes"]["FloorArea"]["value"]) == 120.5
    (comp,) = body["draft"]["components"]
    assert comp["cls"] == "Building"
    assert comp["rows"][0]["id"] == "B1"
    assert float(comp["rows"][0]["FloorArea"]) == 120.5


def test_api_generate_rejects_bad_draft(replica_ws, api_client):
    base = f"/api/workspaces/{_Ctx.id}/replica"
    r = api_client.post(f"{base}/generate", json={"components": []})
    assert r.status_code == 400
