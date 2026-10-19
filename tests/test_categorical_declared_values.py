# SPDX-License-Identifier: Apache-2.0

"""A categorical value is the value the ontology declares, matched by its label.

The Ontology Manager declares the allowed values of a categorical attribute as
named individuals (``OrientationSouth``), each with a label and, when the data
uses a code for it, a ``skos:notation`` (``"S"``). The replica writer finds the
individual a cell names by that code or label, exactly, and never mints a
category IRI from cell text; a value the ontology does not declare is an error.
The payload sends the code back, so the model reads what it always read.
"""
from __future__ import annotations

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from rdflib import OWL, RDF, RDFS, Literal, Namespace, URIRef  # noqa: E402

from backend.ontology_kinds import (  # noqa: E402
    SKOS, category_code, category_label, resolve_category, value_iri, with_core,
)
from backend.ontology_manager import apply_extension_instructions  # noqa: E402
from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)
from backend.workspace.storage import WorkspaceStorage  # noqa: E402

D = Namespace("https://digicities.info/ontology#")
PROJ = "https://x.org/p"
# A declared value lives under its attribute (``value_iri``).
SOUTH = value_iri(D.Orientation, "OrientationSouth")
NORTH = value_iri(D.Orientation, "OrientationNorth")


def _comfort_schema(tmp_path: Path) -> rdflib.Graph:
    """Room with a categorical Orientation whose data codes are S / N, declared
    through the real instruction executor."""
    ops = [
        {"op": "add_component", "name": "Room"},
        {"op": "add_attribute", "name": "Orientation", "type": "Categorical"},
        {"op": "link_attribute", "component": "Room", "attribute": "Orientation"},
        {"op": "add_named_individual", "name": "OrientationSouth", "attribute": "Orientation",
         "annotations": {"label": "South-facing", "notation": ["S"]}},
        {"op": "add_named_individual", "name": "OrientationNorth", "attribute": "Orientation",
         "annotations": {"label": "North-facing", "notation": ["N"]}},
    ]
    report = apply_extension_instructions(
        {"extension": "ext.ttl", "instructions": ops},
        storage=WorkspaceStorage.local(str(tmp_path)), workspace_id="ws")
    assert not [r for r in report["results"] if r["status"] == "error"], report["results"]
    return rdflib.Graph().parse(tmp_path / "ontology" / "extensions" / "ext.ttl", format="turtle")


def _workbook(path: Path, values) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Room"
    ws.cell(row=1, column=1, value="id")
    ws.cell(row=1, column=2, value="Orientation")
    ws.cell(row=2, column=2, value="Categorical")
    for i, value in enumerate(values, start=7):
        ws.cell(row=i, column=1, value=f"R{i}")
        ws.cell(row=i, column=2, value=value)
    wb.save(path)
    return path


def test_the_executor_states_the_data_codes_and_a_rerun_changes_nothing(tmp_path):
    ext = _comfort_schema(tmp_path)
    assert (SOUTH, SKOS.notation, Literal("S")) in ext
    assert (SOUTH, RDFS.label, Literal("South-facing")) in ext
    again = _comfort_schema(tmp_path)
    assert len(again) == len(ext)
    assert len(list(again.objects(SOUTH, SKOS.notation))) == 1


def test_a_value_is_found_by_its_code_then_its_label_never_its_iri(tmp_path):
    g = with_core(_comfort_schema(tmp_path))
    assert resolve_category(g, D.Orientation, "S") == SOUTH
    assert resolve_category(g, D.Orientation, "North-facing") == NORTH
    # The individual's own name is not a code: nothing reads the IRI.
    assert resolve_category(g, D.Orientation, "OrientationSouth") is None
    assert resolve_category(g, D.Orientation, "s") is None
    assert category_code(g, SOUTH) == "S"


def test_two_values_sharing_a_code_is_no_match():
    g = rdflib.Graph()
    g.add((D.Zone, RDFS.subClassOf, D.CategoricalAttribute))
    for v in (D.ZoneA, D.ZoneB):
        g.add((v, RDF.type, OWL.NamedIndividual))
        g.add((v, RDF.type, D.Zone))
        g.add((v, SKOS.notation, Literal("A")))
    assert resolve_category(with_core(g), D.Zone, "A") is None


def test_the_replica_states_the_declared_value(tmp_path):
    ext = _comfort_schema(tmp_path)
    out = tmp_path / "out.ttl"
    process_excel_to_ttl(PROJ, str(_workbook(tmp_path / "w.xlsx", ["S", "N"])), str(out),
                         ontology=ext)
    g = rdflib.Graph().parse(out, format="turtle")
    stated = set(g.objects(None, D.hasCategoricalValue))
    assert stated == {SOUTH, NORTH}
    assert URIRef(str(D) + "S") not in set(g.all_nodes())


def test_a_value_the_ontology_does_not_declare_is_an_error(tmp_path):
    ext = _comfort_schema(tmp_path)
    with pytest.raises(ValueError, match=r"Room\.Orientation.*`W`.*not a declared value"):
        process_excel_to_ttl(PROJ, str(_workbook(tmp_path / "w.xlsx", ["S", "W"])),
                             str(tmp_path / "out.ttl"), ontology=ext)


def test_the_payload_sends_the_code_back(tmp_path):
    from backend.api_submission.ttl_converter import RobustTTL2YAMLProcessor

    ext = _comfort_schema(tmp_path)
    proc = RobustTTL2YAMLProcessor(ontology_graph=ext)
    attr = URIRef(f"{PROJ}/Room/R7/Orientation")
    proc.g.add((attr, RDF.type, D.Orientation))
    proc.g.add((attr, RDF.type, D.CategoricalAttribute))
    proc.g.add((attr, D.hasCategoricalValue, SOUTH))
    proc.view = with_core(rdflib.Graph() + proc.g + ext)   # as loading a scenario builds it
    assert proc._category_value(attr, "Orientation") == "S"


def test_a_value_two_attributes_share_is_declared_for_both(tmp_path):
    ops = [
        {"op": "add_attribute", "name": "HeatingSupply", "type": "Categorical"},
        {"op": "add_attribute", "name": "DHWSupply", "type": "Categorical"},
        {"op": "add_named_individual", "name": "OilHeated", "attribute": "HeatingSupply",
         "annotations": {"notation": ["OilHeated"]}},
        {"op": "add_named_individual", "name": "OilHeated", "attribute": "DHWSupply",
         "annotations": {"notation": ["OilHeated"]}},
    ]
    report = apply_extension_instructions(
        {"extension": "ext.ttl", "instructions": ops},
        storage=WorkspaceStorage.local(str(tmp_path)), workspace_id="ws")
    assert not [r for r in report["results"] if r["status"] == "error"], report["results"]
    g = with_core(rdflib.Graph().parse(tmp_path / "ontology" / "extensions" / "ext.ttl",
                                       format="turtle"))
    # Each attribute has its own value: one never stands for the other.
    heating = resolve_category(g, D.HeatingSupply, "OilHeated")
    dhw = resolve_category(g, D.DHWSupply, "OilHeated")
    assert heating == value_iri(D.HeatingSupply, "OilHeated")
    assert dhw == value_iri(D.DHWSupply, "OilHeated")


def _legacy_extension(tmp_path: Path) -> Path:
    """An extension written before values had their own IRIs: ``dici_onto:<Name>``."""
    g = rdflib.Graph()
    g.add((D.Orientation, RDF.type, OWL.Class))
    g.add((D.Orientation, RDFS.subClassOf, D.CategoricalAttribute))
    g.add((D.OrientationSouth, RDF.type, OWL.NamedIndividual))
    g.add((D.OrientationSouth, RDF.type, D.Orientation))
    g.add((D.OrientationSouth, RDFS.label, Literal("South-facing")))
    g.add((D.OrientationSouth, SKOS.notation, Literal("S")))
    path = tmp_path / "ontology" / "extensions" / "ext.ttl"
    path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(path, format="turtle")
    return path


def test_a_workspace_written_before_still_reads_its_values(tmp_path):
    g = with_core(rdflib.Graph().parse(_legacy_extension(tmp_path), format="turtle"))
    assert resolve_category(g, D.Orientation, "S") == D.OrientationSouth
    assert category_code(g, D.OrientationSouth) == "S"
    assert category_label(g, D.OrientationSouth) == "South-facing"


def test_a_replay_over_an_old_extension_reuses_its_values(tmp_path):
    path = _legacy_extension(tmp_path)
    ops = [{"op": "add_named_individual", "name": "OrientationSouth",
            "attribute": "Orientation", "annotations": {"notation": ["S", "Sud"]}}]
    report = apply_extension_instructions(
        {"extension": "ext.ttl", "instructions": ops},
        storage=WorkspaceStorage.local(str(tmp_path)), workspace_id="ws")
    assert report["results"][0]["status"] == "skipped", report["results"]
    g = with_core(rdflib.Graph().parse(path, format="turtle"))
    assert (SOUTH, None, None) not in g                     # no second copy
    assert resolve_category(g, D.Orientation, "Sud") == D.OrientationSouth


def test_a_value_shows_its_label_not_its_iri(tmp_path):
    g = _comfort_schema(tmp_path)
    assert category_label(g, SOUTH) == "South-facing"
    bare = rdflib.Graph()
    assert category_label(bare, SOUTH) == "OrientationSouth"
    assert category_label(bare, D.CCGT) == "CCGT"


# ── several values on one attribute (Calliope's CHP, 2026-10-19) ──────────────

def test_a_cell_with_several_values_links_each_value_node(tmp_path):
    """`carrier_out: [electricity, heat]`: the attribute node links to each
    declared value node; no string list reaches the graph."""
    ext = _comfort_schema(tmp_path)
    out = tmp_path / "out.ttl"
    process_excel_to_ttl(PROJ, str(_workbook(tmp_path / "w.xlsx", ['["S", "N"]', "S"])), str(out),
                         ontology=ext)
    g = rdflib.Graph().parse(out, format="turtle")
    first = URIRef(f"{PROJ}/Room/R7/Orientation")
    assert set(g.objects(first, D.hasCategoricalValue)) == {SOUTH, NORTH}
    assert not [o for o in g.objects(first, D.hasCategoricalValue) if isinstance(o, Literal)]
    assert set(g.objects(URIRef(f"{PROJ}/Room/R8/Orientation"), D.hasCategoricalValue)) == {SOUTH}


def test_an_undeclared_item_in_a_list_is_an_error(tmp_path):
    ext = _comfort_schema(tmp_path)
    with pytest.raises(ValueError, match=r"`W`.*not a declared value"):
        process_excel_to_ttl(PROJ, str(_workbook(tmp_path / "w.xlsx", ['["S", "W"]'])),
                             str(tmp_path / "out.ttl"), ontology=ext)


def test_the_payload_sends_every_code(tmp_path):
    from backend.api_submission.ttl_converter import RobustTTL2YAMLProcessor

    ext = _comfort_schema(tmp_path)
    proc = RobustTTL2YAMLProcessor(ontology_graph=ext)
    attr = URIRef(f"{PROJ}/Room/R7/Orientation")
    proc.g.add((attr, RDF.type, D.Orientation))
    proc.g.add((attr, RDF.type, D.CategoricalAttribute))
    proc.g.add((attr, D.hasCategoricalValue, SOUTH))
    proc.g.add((attr, D.hasCategoricalValue, NORTH))
    proc.view = with_core(rdflib.Graph() + proc.g + ext)
    assert proc._category_value(attr, "Orientation") == ["N", "S"]


def test_several_values_round_trip_through_the_model(tmp_path):
    """Loaded back from the graph the attribute carries a list of value IRIs (and
    codes), and is written back as one link per value."""
    from backend.replica_builder import graph_loader
    from backend.replica_builder.utils.ttl_attribute_helpers import category_term
    ext = _comfort_schema(tmp_path)
    data = rdflib.Graph()
    node = URIRef(f"{PROJ}/Room/R7/Orientation")
    data.add((node, RDF.type, D.Orientation))
    data.add((node, RDF.type, D.CategoricalAttribute))
    data.add((node, D.hasCategoricalValue, SOUTH))
    data.add((node, D.hasCategoricalValue, NORTH))
    got = graph_loader.parse_single_attribute(data, node, schema=graph_loader.schema_view(data, ext))
    assert got["category_value"] == sorted([str(NORTH), str(SOUTH)])
    assert got["category_code"] == ["N", "S"]
    assert category_term(got["category_value"]) == f"<{NORTH}> , <{SOUTH}>"
    assert category_term(str(SOUTH)) == f"<{SOUTH}>"
    assert " , " not in category_term("[not json")      # an odd value stays one term


def test_the_explorer_lists_every_value_by_its_label():
    from backend.explorer.attributes import AttributeProcessor
    p = AttributeProcessor()
    data = {"properties": {}, "type_uris": set(),
            "category_values": {str(SOUTH): "South-facing", str(NORTH): "North-facing"}}
    assert p._process_categorical_attribute(data, "Orientation") == "North-facing, South-facing"
