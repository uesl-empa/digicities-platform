# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Building an ontology extension in the proper sequence.

The naming rules (``backend.ontology_manager.naming``), the class tree
(``hierarchy``), the Ontology Manager operations that enforce them, the
extension-instruction replay and its dry run, and the REST routes. The worked
example is the one users ask for: horizontal- and vertical-axis wind turbines
under a WindTurbine under the core Turbine, built as a hierarchy in the
workspace extension.

Assertions read the persisted extension with rdflib — never string matching.
"""
from __future__ import annotations

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import OWL, RDF, RDFS, Namespace  # noqa: E402

from backend.ontology_manager import (  # noqa: E402
    OntologyFunctions, apply_extension_instructions, check_extension_instructions)
from backend.ontology_manager import hierarchy  # noqa: E402
from backend.ontology_manager.naming import (  # noqa: E402
    MAX_CLASS_NAME, check_class_name, check_property_name, class_name, core_terms,
    property_name)
from backend.workspace.storage import WorkspaceStorage  # noqa: E402

DICI = Namespace("https://digicities.info/ontology#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
EXT = "test_ext.ttl"


@pytest.fixture()
def funcs(tmp_path):
    of = OntologyFunctions(storage=WorkspaceStorage.local(str(tmp_path)), workspace_id="ws")
    ok, msg = of.create_new_extension("test_ext")
    assert ok, msg
    ok, msg = of.load_extension_and_update(EXT)
    assert ok, msg
    return of


@pytest.fixture(scope="module")
def core():
    of = OntologyFunctions.__new__(OntologyFunctions)
    return OntologyFunctions.load_core_ontology(of)


def _ext(funcs):
    return funcs.load_extension(EXT)


def _parents(g, name):
    return {str(o).split("#")[-1] for o in g.objects(DICI[name], RDFS.subClassOf)}


# ── naming rules ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,name", [
    ("wind turbine", "WindTurbine"), ("wind_turbine", "WindTurbine"),
    ("Wind Turbine", "WindTurbine"), ("WindTurbine", "WindTurbine"),
    ("CO2 sensor", "CO2Sensor"), ("PVModule", "PVModule"), ("--", ""),
])
def test_class_name_from_any_label(label, name):
    assert class_name(label) == name


def test_property_name_is_camel_case():
    assert property_name("part of wind park") == "partOfWindPark"
    assert check_property_name("partOfWindPark").ok
    assert not check_property_name("PartOf").ok


def test_class_name_rules(core):
    assert check_class_name("WindTurbine", core=core).ok
    assert "PascalCase" in check_class_name("windTurbine").message()
    assert "PascalCase" in check_class_name("Wind_Turbine").message()
    assert "reserved" in check_class_name("WindTurbineAttribute").message()
    long = "A" + "b" * MAX_CLASS_NAME
    assert f"at most {MAX_CLASS_NAME}" in check_class_name(long).message()
    assert "already declared" in check_class_name("X", existing={"X"}).message()
    # a core term is never redeclared
    assert "already a core class" in check_class_name("Turbine", core=core).message()


def test_a_core_alternative_label_is_flagged(core):
    """A new class named after a core class's alternative label is probably the same
    concept: warned, not refused."""
    terms = core_terms(core)
    term, alt = next((t, lb) for t, i in sorted(terms.items()) if i["kind"] == "class"
                     for lb in sorted(i["labels"])
                     if class_name(lb) not in terms and class_name(lb)[:1].isupper()
                     and len(class_name(lb)) <= MAX_CLASS_NAME)
    chk = check_class_name(class_name(alt), core=core, label=alt)
    assert chk.ok and term in [t for t, _h in chk.similar]


# ── the class tree ─────────────────────────────────────────────────────────────
def test_core_tree_queries(core):
    assert hierarchy.is_subclass_of(core, "Turbine", "Component")
    assert "Component" in hierarchy.ancestors(core, "Turbine")
    assert "Turbine" in hierarchy.descendants(core, "Component")
    assert hierarchy.would_cycle(core, "Component", "Turbine")
    cands = [c["name"] for c in hierarchy.parent_candidates(core, "horizontal axis wind turbine")]
    assert "Turbine" in cands
    t = hierarchy.tree(core, "Converter", depth=3)
    assert any(c["name"] == "Turbine" for c in _walk(t))


@pytest.mark.parametrize("text,noise", [
    # "building" occurs in the core only as a modifier or after a preposition
    ("Building", ["CompositeWeatherObservation", "LiquidFuel", "Flow", "EnergyConsumer",
                  "Location", "Controller"]),
    ("weather station", ["EnergyConsumer"]),          # its example is an EV charging station
])
def test_parent_candidates_are_matched_by_head_noun(core, text, noise):
    names = [c["name"] for c in hierarchy.parent_candidates(core, text)]
    assert not set(names) & set(noise), names
    assert "Component" not in names                   # the root is the default, not a choice


def test_parent_candidates_still_find_by_name_label_and_example(core):
    assert hierarchy.parent_candidates(core, "wind turbines")[0]["name"] == "Turbine"
    assert "Turbine" not in [c["name"] for c in hierarchy.parent_candidates(core, "gas pipe")]


def test_noun_phrase_heads():
    from backend.ontology_manager.hierarchy import _head
    assert _head("A building heating load") == ("load", {"building", "heating"})
    assert _head("Electricity flow from the grid to a building") == ("flow", {"electricity"})
    assert _head("Building Management System") == ("system", {"building", "management"})
    assert _head("WindTurbine") == ("turbine", {"wind"})
    assert _head("Buildings") == ("building", set())



def _walk(node):
    yield node
    for c in node["children"]:
        yield from _walk(c)


# ── the Ontology Manager operations enforce the sequence ─────────────────────
def test_add_component_forms_the_name_and_checks_the_parent(funcs):
    ok, msg = funcs.add_component(EXT, "wind turbine", "Turbine")
    assert ok, msg
    assert "Turbine" in _parents(_ext(funcs), "WindTurbine")
    ok, msg = funcs.add_component(EXT, "Turbine", "Component")
    assert not ok and "core class" in msg                       # never redefine core
    ok, msg = funcs.add_component(EXT, "Blade", "RotorAssembly")
    assert not ok and "add the parent first" in msg              # parent must exist
    ok, msg = funcs.add_component(EXT, "wind turbine", "Turbine")
    assert not ok and "already declared" in msg


def test_turbine_hierarchy_top_down(funcs):
    assert funcs.add_component(EXT, "WindTurbine", "Turbine")[0]
    for sub in ("HorizontalAxisWindTurbine", "VerticalAxisWindTurbine"):
        ok, msg = funcs.add_component(EXT, sub, "WindTurbine")
        assert ok, msg
    g = funcs.merge_ontologies(EXT)
    assert hierarchy.is_subclass_of(g, "HorizontalAxisWindTurbine", "Turbine")
    assert hierarchy.is_subclass_of(g, "VerticalAxisWindTurbine", "Component")
    # siblings with their own attributes
    assert funcs.add_attribute(EXT, "Physical", "Tip Speed Ratio", qudt_unit="UNITLESS")[0]
    ok, msg = funcs.link_attribute(EXT, str(DICI.HorizontalAxisWindTurbine),
                                   str(DICI.TipSpeedRatio))
    assert ok, msg
    ext = _ext(funcs)
    # the predicate instance data uses is declared (has<Comp><Attr>Attribute)
    data_prop = DICI.hasHorizontalAxisWindTurbineTipSpeedRatioAttribute
    assert (data_prop, RDF.type, OWL.ObjectProperty) in ext
    assert (data_prop, RDFS.subPropertyOf, DICI.hasHorizontalAxisWindTurbineAttribute) in ext
    # the tree shows the structure
    tree = funcs.component_tree(EXT, "Turbine")
    wt = next(n for n in _walk(tree) if n["name"] == "WindTurbine")
    assert {c["name"] for c in wt["children"]} == {"HorizontalAxisWindTurbine",
                                                   "VerticalAxisWindTurbine"}


def test_remove_needs_the_subclasses_moved_first(funcs):
    funcs.add_component(EXT, "WindTurbine", "Turbine")
    funcs.add_component(EXT, "HorizontalAxisWindTurbine", "WindTurbine")
    ok, msg = funcs.remove_component(EXT, str(DICI.WindTurbine))
    assert not ok and "HorizontalAxisWindTurbine" in msg
    assert funcs.remove_component(EXT, str(DICI.HorizontalAxisWindTurbine))[0]
    assert funcs.remove_component(EXT, str(DICI.WindTurbine))[0]
    assert (DICI.WindTurbine, RDF.type, OWL.Class) not in _ext(funcs)


def test_remove_deletes_only_what_the_class_owns(funcs):
    """Removing `Wind` used to wipe everything whose name starts `hasWind…`."""
    funcs.add_component(EXT, "Wind", "Component")
    funcs.add_component(EXT, "WindTurbine", "Turbine")
    funcs.add_attribute(EXT, "Physical", "Hub Height", qudt_unit="M")
    funcs.link_attribute(EXT, str(DICI.WindTurbine), str(DICI.HubHeight))
    assert funcs.remove_component(EXT, str(DICI.Wind))[0]
    ext = _ext(funcs)
    assert (DICI.hasWindTurbineHubHeightAttribute, RDF.type, OWL.ObjectProperty) in ext
    assert (DICI.hasWindTurbineAttribute, RDF.type, OWL.ObjectProperty) in ext
    assert (DICI.hasWindAttribute, RDF.type, OWL.ObjectProperty) not in ext


def test_remove_attribute_deletes_only_its_own_properties(funcs):
    """Removing `Area` used to hit every predicate containing 'Area'."""
    funcs.add_component(EXT, "Plot", "Component")
    for label in ("Area", "Floor Area"):
        funcs.add_attribute(EXT, "Physical", label, qudt_unit="M2")
    for a in ("Area", "FloorArea"):
        funcs.link_attribute(EXT, str(DICI.Plot), str(DICI[a]))
    assert funcs.remove_attribute(EXT, str(DICI.Area))[0]
    ext = _ext(funcs)
    assert (DICI.hasPlotFloorAreaAttribute, RDF.type, OWL.ObjectProperty) in ext
    assert (DICI.hasPlotAreaAttribute, RDF.type, OWL.ObjectProperty) not in ext
    assert (DICI.hasPlotAttribute, RDF.type, OWL.ObjectProperty) in ext   # general stays


def test_reparent_checks(funcs):
    funcs.add_component(EXT, "WindTurbine", "Turbine")
    funcs.add_component(EXT, "HorizontalAxisWindTurbine", "WindTurbine")
    ok, msg = funcs.change_component_parent(EXT, str(DICI.WindTurbine),
                                            str(DICI.HorizontalAxisWindTurbine))
    assert not ok and "its own subclass" in msg
    ok, msg = funcs.change_component_parent(EXT, str(DICI.Turbine), str(DICI.Component))
    assert not ok and "core class" in msg
    ok, msg = funcs.change_component_parent(EXT, str(DICI.WindTurbine), str(DICI.Nowhere))
    assert not ok and "add it first" in msg
    ok, msg = funcs.change_component_parent(EXT, str(DICI.WindTurbine), str(DICI.Converter))
    assert ok, msg
    assert _parents(_ext(funcs), "WindTurbine") == {"Converter"}


def test_rename_cascades_to_everything_generated(funcs):
    funcs.add_component(EXT, "GlobalWindAtlasSite", "Location")
    funcs.add_component(EXT, "WindTurbine", "Turbine")
    funcs.add_component(EXT, "SiteArray", "GlobalWindAtlasSite")
    funcs.add_attribute(EXT, "SimpleValue", "Roughness")
    funcs.link_attribute(EXT, str(DICI.GlobalWindAtlasSite), str(DICI.Roughness))
    apply_extension_instructions({"extension": EXT, "instructions": [
        {"op": "add_object_property", "name": "partOfGlobalWindAtlasSite",
         "parent": "linksComponent", "domain": "WindTurbine", "range": "GlobalWindAtlasSite"}]},
        storage=funcs.storage)
    ok, msg = funcs.rename_component(EXT, str(DICI.GlobalWindAtlasSite), "Wind Park")
    assert ok, msg
    ext = _ext(funcs)
    assert (DICI.WindPark, RDF.type, OWL.Class) in ext
    assert (DICI.GlobalWindAtlasSite, None, None) not in ext
    assert (None, None, DICI.GlobalWindAtlasSite) not in ext
    assert (DICI.GlobalWindAtlasSiteAttribute, None, None) not in ext
    assert "WindPark" in _parents(ext, "SiteArray")                       # child follows
    assert (DICI.hasWindParkRoughnessAttribute, RDFS.domain, DICI.WindPark) in ext
    assert (DICI.hasWindParkRoughnessAttribute, RDFS.range, DICI.Roughness) in ext
    assert (DICI.hasWindParkAttribute, RDFS.range, DICI.WindParkAttribute) in ext
    assert (DICI.WindParkAttribute, RDF.type, OWL.Class) in ext
    # A link property points at the renamed class; its name is the user's and
    # stays (nothing is renamed by matching its spelling).
    assert (DICI.partOfGlobalWindAtlasSite, RDFS.range, DICI.WindPark) in ext
    assert str(next(ext.objects(DICI.WindPark, RDFS.label))) == "Wind Park"
    ok, msg = funcs.rename_component(EXT, str(DICI.WindPark), "Turbine")
    assert not ok and "core class" in msg


# ── the instruction replay follows the same sequence ─────────────────────────
def _instr(ops):
    return {"version": 1, "workspace": "ws", "extension": EXT, "instructions": ops}


def test_instructions_build_a_hierarchy_top_down(funcs):
    rep = apply_extension_instructions(_instr([
        {"op": "add_component", "name": "WindTurbine", "parent": "Turbine",
         "annotations": {"definition": "A turbine driven by wind.",
                         "examples": ["Vestas V136"]}},
        {"op": "add_component", "name": "HorizontalAxisWindTurbine", "parent": "WindTurbine"},
        {"op": "add_component", "name": "VerticalAxisWindTurbine", "parent": "WindTurbine"},
    ]), storage=funcs.storage)
    assert rep["ok"], rep["results"]
    ext = _ext(funcs)
    assert _parents(ext, "VerticalAxisWindTurbine") == {"WindTurbine"}
    assert (DICI.WindTurbine, SKOS.definition, None) in ext
    assert (DICI.WindTurbine, SKOS.example, None) in ext


def test_instructions_refuse_out_of_sequence_ops(funcs):
    rep = apply_extension_instructions(_instr([
        {"op": "add_component", "name": "HorizontalAxisWindTurbine", "parent": "WindTurbine"},
        {"op": "add_component", "name": "Turbine", "parent": "Component"},
        {"op": "add_component", "name": "wind_park", "parent": "Location"},
        {"op": "add_attribute", "name": "Efficiency", "type": "SimpleValue"},
        {"op": "add_attribute", "name": "rotor diameter", "type": "Physical", "qudt_unit": "M"},
        {"op": "link_attribute", "component": "Turbine", "attribute": "RotorDiameter"},
        {"op": "add_object_property", "name": "PartOfPark", "domain": "Turbine"},
    ]), storage=funcs.storage)
    by = [(r["op"], r["target"], r["status"]) for r in rep["results"]]
    assert by[0] == ("add_component", "HorizontalAxisWindTurbine", "error")   # parent first
    assert by[1][2] == "skipped"                                              # core reused
    assert by[2][2] == "error"                                                # not PascalCase
    assert by[3][2] == "skipped"                                              # core attribute
    assert by[4][2] == "error"                                                # bad name
    assert by[5][2] == "error"                                  # links to a refused attribute
    assert by[6][2] == "error"                                  # property not camelCase
    assert "declare it first" in rep["results"][0]["message"]
    assert not rep["ok"]
    assert (DICI.Turbine, RDF.type, OWL.Class) not in _ext(funcs)            # core untouched


def test_instructions_move_rename_remove(funcs):
    base = [{"op": "add_component", "name": "WindTurbine", "parent": "Turbine"},
            {"op": "add_component", "name": "HAWT", "parent": "Component"}]
    assert apply_extension_instructions(_instr(base), storage=funcs.storage)["ok"]
    rep = apply_extension_instructions(_instr([
        {"op": "change_parent", "name": "HAWT", "parent": "WindTurbine"},
        {"op": "rename_component", "name": "HAWT", "new_name": "HorizontalAxisWindTurbine"},
        {"op": "change_parent", "name": "WindTurbine", "parent": "HorizontalAxisWindTurbine"},
        {"op": "remove_component", "name": "WindTurbine"},
        {"op": "annotate", "name": "HorizontalAxisWindTurbine",
         "annotations": {"comment": "Rotor axis parallel to the wind."}},
    ]), storage=funcs.storage)
    st = [r["status"] for r in rep["results"]]
    assert st == ["applied", "applied", "error", "error", "applied"], rep["results"]
    ext = _ext(funcs)
    assert _parents(ext, "HorizontalAxisWindTurbine") == {"WindTurbine"}
    # a replay of the same file is idempotent
    rep2 = apply_extension_instructions(_instr([
        {"op": "change_parent", "name": "HorizontalAxisWindTurbine", "parent": "WindTurbine"},
        {"op": "rename_component", "name": "HAWT", "new_name": "HorizontalAxisWindTurbine"},
    ]), storage=funcs.storage)
    assert [r["status"] for r in rep2["results"]] == ["skipped", "skipped"]


def test_dry_run_checks_without_writing(funcs):
    before = len(_ext(funcs))
    rep = check_extension_instructions(_instr([
        {"op": "add_component", "name": "WindTurbine", "parent": "Turbine"},
        {"op": "add_component", "name": "HorizontalAxisWindTurbine", "parent": "WindTurbine"},
        {"op": "add_component", "name": "Blade", "parent": "Rotor"},
    ]), storage=funcs.storage)
    assert [r["status"] for r in rep["results"]] == ["ok", "ok", "error"]
    assert rep["parents"]["HorizontalAxisWindTurbine"] == ["WindTurbine"]
    assert len(_ext(funcs)) == before                                          # nothing written


# ── REST ─────────────────────────────────────────────────────────────────────
class _Ctx:
    id = "ontows"
    name = "Onto WS"
    graphdb_repository = "ontows"


@pytest.fixture()
def api(tmp_path, monkeypatch, api_app, api_client):
    monkeypatch.setenv("USECASES_DIR", str(tmp_path))
    from apps.api.deps import get_ctx
    root = tmp_path / _Ctx.id
    root.mkdir()
    ctx = _Ctx()
    ctx.storage = WorkspaceStorage.local(str(root))
    api_app.dependency_overrides[get_ctx] = lambda: ctx
    base = f"/api/workspaces/{_Ctx.id}/ontology"
    assert api_client.post(f"{base}/extension/create", json={"name": "test_ext"}).status_code == 200
    return api_client, base


@pytest.mark.api
def test_rest_event_attribute_rename_tree_and_checks(api):
    client, base = api
    r = client.post(f"{base}/attribute/add", json={
        "extension": EXT, "attribute_type": "Event", "label": "Commissioned",
        "temporal_precision": "Date"})
    assert r.status_code == 200, r.text                         # Event used to always fail
    r = client.post(f"{base}/component/add", json={
        "extension": EXT, "label": "Global Wind Atlas Site", "parent": "Location"})
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/component/rename", json={
        "extension": EXT, "uri": str(DICI.GlobalWindAtlasSite), "new_label": "WindPark"})
    assert r.status_code == 200, r.text
    tree = client.get(f"{base}/tree", params={"extension": EXT, "root": "Location"}).json()
    assert any(n["name"] == "WindPark" for n in _walk(tree))
    chk = client.get(f"{base}/names/check", params={"extension": EXT, "label": "turbine"}).json()
    assert chk["name"] == "Turbine" and not chk["ok"]
    sugg = client.get(f"{base}/parents/suggest",
                      params={"extension": EXT, "text": "wind turbine"}).json()
    assert any(s["name"] == "Turbine" for s in sugg)
    r = client.post(f"{base}/component/add", json={
        "extension": EXT, "label": "Turbine", "parent": "Component"})
    assert r.status_code == 400 and "core class" in r.json()["detail"]
