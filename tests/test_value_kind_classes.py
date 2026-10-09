# SPDX-License-Identifier: Apache-2.0

"""Data-path and identifier attributes have value-kind classes of their own.

``ResourceAttribute`` used to be both the category of the ``Resource``
component and the value kind of a data-path attribute, and an identifier had
no value-kind class at all (so identifier classes sat under a component's
category with nothing saying what shape their value has). Core v0.6.0 adds
``DataPathAttribute`` and ``IdentifierAttribute``; ``ResourceAttribute`` is
only a category.
"""
from __future__ import annotations

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
openpyxl = pytest.importorskip("openpyxl")

from rdflib import RDF, Graph, URIRef  # noqa: E402

from workbook_schema import declare_workbook  # noqa: E402
from backend.ontology_kinds import (  # noqa: E402
    DICI, KIND_CLASS, AttributeKind, core_graph, kind_for_class, kind_of_node, with_core,
)
from backend.ontology_scaffold import category_of, check_pattern  # noqa: E402
from backend.replica_builder.utils.create_class_and_attribute_graph import (  # noqa: E402
    process_excel_to_ttl,
)

PROJ = "https://x.org/p"
M1 = URIRef(f"{PROJ}/Machine/M1")


def _workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    m = wb.create_sheet("Machine")
    for c, (name, atype) in enumerate([("id", None), ("DataFile", "Resource"),
                                       ("Code", "Identifier")], start=1):
        m.cell(row=1, column=c, value=name)
        if atype:
            m.cell(row=2, column=c, value=atype)
    for c, v in enumerate(["M1", "data/m1.csv", "M-001"], start=1):
        m.cell(row=7, column=c, value=v)
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("kinds")
    xlsx = _workbook(tmp / "wb.xlsx")
    schema = declare_workbook(xlsx, tmp / "ws")
    ttl = tmp / "wb.ttl"
    process_excel_to_ttl(PROJ, str(xlsx), str(ttl), ontology=schema)
    data = Graph().parse(ttl, format="turtle")
    return schema, data


def test_resource_attribute_is_only_a_category():
    core = with_core(Graph())
    assert DICI.ResourceAttribute not in set(KIND_CLASS.values())
    assert kind_for_class(DICI.ResourceAttribute) is None
    assert category_of(core, DICI.Resource) == DICI.ResourceAttribute
    assert check_pattern(core_graph()) == []


def test_the_two_new_kind_classes_resolve_to_their_kinds():
    assert kind_for_class(DICI.DataPathAttribute) is AttributeKind.RESOURCE
    assert kind_for_class(DICI.IdentifierAttribute) is AttributeKind.IDENTIFIER
    g = Graph()
    g.add((URIRef(f"{PROJ}/n1"), RDF.type, DICI.ResourceAttribute))
    # A node typed only with the Resource category has no value kind.
    assert kind_of_node(with_core(g), URIRef(f"{PROJ}/n1")) is None


def test_a_resource_column_builds_a_data_path_attribute(built):
    schema, data = built
    node = URIRef(f"{M1}/DataFile")
    assert (node, RDF.type, DICI.DataPathAttribute) in data
    view = with_core(schema + data)
    assert kind_of_node(view, node) is AttributeKind.RESOURCE
    assert check_pattern(with_core(schema)) == []


def test_an_identifier_column_builds_an_identifier_attribute(built):
    schema, data = built
    (node,) = list(data.objects(M1, DICI.hasIdentifier))
    assert (node, RDF.type, DICI.IdentifierAttribute) in data
    view = with_core(schema + data)
    assert kind_of_node(view, node) is AttributeKind.IDENTIFIER                 # by type
    assert kind_of_node(view, node, DICI.hasIdentifier) is AttributeKind.IDENTIFIER
