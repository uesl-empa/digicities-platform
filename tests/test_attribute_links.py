# SPDX-License-Identifier: Apache-2.0

"""A link the data uses and the ontology lacks gets declared, by the rules of the
scaffold, whichever route wrote it. Runs against the real vendored core."""
from __future__ import annotations

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Namespace
from rdflib.graph import ReadOnlyGraphAggregate

from backend.ontology_kinds import core_graph, is_attribute_predicate, with_core
from backend.ontology_scaffold import (
    attributes_of, check_pattern, declare_used_links, link_predicate, undeclared_links,
)
from backend.scenario_builder.emitter import _attribute_predicate
from backend.workspace.attribute_links import declare_attribute_links, declare_in_folder
from backend.workspace.storage import WorkspaceStorage

DICI = Namespace("https://digicities.info/ontology#")
EXT = """
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
dici_onto:Shed a owl:Class ; rdfs:subClassOf dici_onto:Component .
dici_onto:BikeShed a owl:Class ; rdfs:subClassOf dici_onto:Shed .
dici_onto:CarShed a owl:Class ; rdfs:subClassOf dici_onto:Shed .
dici_onto:DoorCount a owl:Class ; rdfs:subClassOf dici_onto:SimpleValueAttribute .
dici_onto:RoofType a owl:Class ; rdfs:subClassOf dici_onto:CategoricalAttribute .
dici_onto:Flat a owl:Class ; rdfs:subClassOf dici_onto:RoofType .
dici_onto:Forecast a owl:Class ; rdfs:subClassOf dici_onto:ResourceAttribute .
"""
PX = """@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix p: <https://digicities.info/proj/w/> .
"""


def _schema(extra=""):
    return core_graph() + Graph().parse(data=EXT + extra, format="turtle")


def _data(body):
    return Graph().parse(data=PX + body, format="turtle")


def _declare(schema, data):
    write = Graph()
    return write, declare_used_links(ReadOnlyGraphAggregate([write, schema]), write, data)


def test_a_used_link_is_declared_by_the_rules_of_the_scaffold():
    schema = _schema()
    write, (declared, skipped) = _declare(schema, _data("""
        p:s a dici_onto:Shed ; dici_onto:hasShedDoorCountAttribute p:s_d .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute ."""))
    assert declared == [DICI.hasShedDoorCountAttribute] and not skipped
    view = schema + write
    pred = DICI.hasShedDoorCountAttribute
    assert (pred, RDF.type, OWL.ObjectProperty) in view
    assert (pred, RDFS.domain, DICI.Shed) in view and (pred, RDFS.range, DICI.DoorCount) in view
    assert is_attribute_predicate(view, pred)
    assert link_predicate(view, DICI.Shed, DICI.DoorCount) == pred
    assert DICI.DoorCount in attributes_of(view, DICI.Shed)
    assert check_pattern(view, [DICI.Shed]) == []


def test_the_name_says_nothing_only_the_types_do():
    """A predicate that does not follow the naming pattern is declared under its
    own name, and a component-to-component link is left out."""
    schema = _schema()
    write, (declared, _) = _declare(schema, _data("""
        p:s a dici_onto:Shed ; dici_onto:doors p:s_d ; dici_onto:nextTo p:t .
        p:t a dici_onto:Shed .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute ."""))
    assert declared == [DICI.doors]
    assert (DICI.nextTo, None, None) not in write


def test_a_declared_link_is_left_alone():
    extra = """
    dici_onto:hasShedAttribute a owl:ObjectProperty ; rdfs:domain dici_onto:Shed ;
        rdfs:subPropertyOf dici_onto:hasComponentAttribute .
    dici_onto:hasShedDoorCountAttribute a owl:ObjectProperty ;
        rdfs:domain dici_onto:Shed ; rdfs:range dici_onto:DoorCount ;
        rdfs:subPropertyOf dici_onto:hasShedAttribute ."""
    data = _data("""
        p:s a dici_onto:Shed ; dici_onto:hasShedDoorCountAttribute p:s_d .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute .""")
    assert undeclared_links(_schema(extra), data) == {}


def test_a_value_class_is_not_the_attribute():
    schema = _schema()
    write, (declared, _) = _declare(schema, _data("""
        p:s a dici_onto:Shed ; dici_onto:hasShedRoofTypeAttribute p:s_r .
        p:s_r a dici_onto:RoofType, dici_onto:Flat, dici_onto:CategoricalAttribute ."""))
    assert declared == [DICI.hasShedRoofTypeAttribute]
    assert (DICI.hasShedRoofTypeAttribute, RDFS.range, DICI.RoofType) in write


def test_a_link_used_by_two_classes_belongs_to_their_nearest_common_class():
    schema = _schema()
    write, (declared, _) = _declare(schema, _data("""
        p:b a dici_onto:BikeShed ; dici_onto:doors p:b_d .
        p:c a dici_onto:CarShed ; dici_onto:doors p:c_d .
        p:b_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute .
        p:c_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute ."""))
    assert declared == [DICI.doors]
    assert (DICI.doors, RDFS.domain, DICI.Shed) in write


def test_an_attribute_with_only_a_kind_class_is_not_guessed_at():
    data = _data("""
        p:s a dici_onto:Shed ; dici_onto:hasThing p:s_d .
        p:s_d a dici_onto:SimpleValueAttribute .""")
    assert undeclared_links(_schema(), data) == {}


def test_a_second_name_for_a_declared_link_becomes_its_sub_property():
    extra = """
    dici_onto:ShedAttribute a owl:Class ; rdfs:subClassOf dici_onto:ComponentAttribute .
    dici_onto:DoorCount rdfs:subClassOf dici_onto:ShedAttribute .
    dici_onto:hasShedAttribute a owl:ObjectProperty ; rdfs:domain dici_onto:Shed ;
        rdfs:range dici_onto:ShedAttribute ;
        rdfs:subPropertyOf dici_onto:hasComponentAttribute .
    dici_onto:hasShedDoorCountAttribute a owl:ObjectProperty ;
        rdfs:domain dici_onto:Shed ; rdfs:range dici_onto:DoorCount ;
        rdfs:subPropertyOf dici_onto:hasShedAttribute ."""
    schema = _schema(extra)
    write, (declared, skipped) = _declare(schema, _data("""
        p:b a dici_onto:BikeShed ; dici_onto:doors p:b_d .
        p:b_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute ."""))
    assert declared == [DICI.doors] and not skipped
    view = schema + write
    assert (DICI.doors, RDFS.subPropertyOf, DICI.hasShedDoorCountAttribute) in view
    assert is_attribute_predicate(view, DICI.doors)
    assert link_predicate(view, DICI.BikeShed, DICI.DoorCount) == DICI.hasShedDoorCountAttribute
    assert check_pattern(view, [DICI.Shed, DICI.BikeShed]) == []


def test_two_attribute_classes_on_one_link_are_reported_and_not_declared():
    write, (declared, skipped) = _declare(_schema(), _data("""
        p:s a dici_onto:Shed ; dici_onto:has p:s_d, p:s_f .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute .
        p:s_f a dici_onto:Forecast, dici_onto:ResourceAttribute ."""))
    assert declared == [] and "several attribute classes" in skipped[0]


# -- the workspace ---------------------------------------------------------------

@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "ontology" / "extensions").mkdir(parents=True)
    (tmp_path / "ontology" / "extensions" / "own.ttl").write_text(EXT, encoding="utf-8")
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.ttl").write_text(PX + """
        p:s a dici_onto:Shed ; dici_onto:hasShedDoorCountAttribute p:s_d .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute .
    """, encoding="utf-8")
    return tmp_path


def _extension(folder):
    return Graph().parse(folder / "ontology" / "extensions" / "own.ttl", format="turtle")


def test_the_file_gets_the_declaration_and_a_second_run_changes_nothing(workspace):
    assert declare_in_folder(str(workspace)) == ["hasShedDoorCountAttribute"]
    ext = _extension(workspace)
    assert (DICI.hasShedDoorCountAttribute, RDFS.domain, DICI.Shed) in ext
    assert (DICI.Shed, RDF.type, OWL.Class) in ext
    first = (workspace / "ontology" / "extensions" / "own.ttl").read_bytes()
    assert declare_in_folder(str(workspace)) == []
    assert (workspace / "ontology" / "extensions" / "own.ttl").read_bytes() == first


def test_what_is_already_written_stays_as_it_is(workspace):
    path = workspace / "ontology" / "extensions" / "own.ttl"
    path.write_text("# A note from the author.\n" + EXT, encoding="utf-8")
    declare_in_folder(str(workspace))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# A note from the author.\n" + EXT.rstrip())
    assert "hasShedDoorCountAttribute" in text


def test_a_workspace_without_an_extension_gets_one(tmp_path):
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.ttl").write_text(PX + """
        p:s a dici_onto:Location ; dici_onto:used p:s_d .
        p:s_d a dici_onto:SetPoint, dici_onto:SimpleValueAttribute .
    """, encoding="utf-8")
    assert declare_in_folder(str(tmp_path)) == ["used"]
    assert (tmp_path / "ontology" / "extensions" / f"{tmp_path.name}_extension.ttl").exists()


def test_a_class_nobody_declares_stays_unknown(tmp_path):
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.ttl").write_text(PX + """
        p:s a dici_onto:Unknown ; dici_onto:used p:s_d .
        p:s_d a dici_onto:SetPoint, dici_onto:SimpleValueAttribute .
    """, encoding="utf-8")
    assert declare_in_folder(str(tmp_path)) == []


def test_a_fault_in_the_ontology_does_not_stop_the_load(tmp_path):
    (tmp_path / "ontology" / "extensions").mkdir(parents=True)
    (tmp_path / "ontology" / "extensions" / "own.ttl").write_text(EXT + """
        dici_onto:CatA a owl:Class ; rdfs:subClassOf dici_onto:ComponentAttribute .
        dici_onto:CatB a owl:Class ; rdfs:subClassOf dici_onto:ComponentAttribute .
        dici_onto:hasShedAttribute a owl:ObjectProperty ; rdfs:domain dici_onto:Shed ;
            rdfs:range dici_onto:CatA, dici_onto:CatB ;
            rdfs:subPropertyOf dici_onto:hasComponentAttribute .
    """, encoding="utf-8")
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.ttl").write_text(PX + """
        p:s a dici_onto:Shed ; dici_onto:doors p:s_d .
        p:s_d a dici_onto:DoorCount, dici_onto:SimpleValueAttribute .
    """, encoding="utf-8")
    assert declare_in_folder(str(tmp_path)) == []


def test_a_file_that_cannot_be_written_still_gives_the_load_its_declarations(workspace):
    class ReadOnly(WorkspaceStorage):
        def write_text(self, *a, **k):
            raise OSError("read-only")

    base = WorkspaceStorage.local(str(workspace))
    base.__class__ = ReadOnly
    schema = _schema()
    data = Graph().parse(workspace / "scenarios" / "a.ttl", format="turtle")
    assert declare_attribute_links(base, schema, data, "w") == ["hasShedDoorCountAttribute"]
    assert is_attribute_predicate(schema, DICI.hasShedDoorCountAttribute)
    assert (DICI.hasShedDoorCountAttribute, None, None) not in _extension(workspace)


# -- the scenario emitter --------------------------------------------------------

def test_the_emitter_uses_the_declared_predicate_of_the_nearest_ancestor():
    extra = """
    dici_onto:hasShedAttribute a owl:ObjectProperty ; rdfs:domain dici_onto:Shed ;
        rdfs:subPropertyOf dici_onto:hasComponentAttribute .
    dici_onto:shedDoors a owl:ObjectProperty ;
        rdfs:domain dici_onto:Shed ; rdfs:range dici_onto:DoorCount ;
        rdfs:subPropertyOf dici_onto:hasShedAttribute ."""
    ext = Graph().parse(data=EXT + extra, format="turtle")
    view = with_core(ext)
    assert _attribute_predicate(view, "BikeShed", "DoorCount") == "shedDoors"


def test_the_emitter_falls_back_to_the_scaffold_name_without_a_declaration():
    view = with_core(Graph().parse(data=EXT, format="turtle"))
    assert _attribute_predicate(view, "Shed", "DoorCount") == "hasShedDoorCountAttribute"
    assert _attribute_predicate(None, "Shed", "DoorCount") == "hasShedDoorCountAttribute"
