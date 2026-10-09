# SPDX-License-Identifier: Apache-2.0

"""A categorical attribute's value is an IRI, stated with hasCategoricalValue.

Writers state ``<attr> dici_onto:hasCategoricalValue <category>`` and no longer
type the attribute node with the category. Readers take the stated value; data
written before that (the category as an extra rdf:type) still reads through the
fallback until the workspace is rebuilt.
"""
from __future__ import annotations

import pandas as pd
import rdflib
from rdflib import RDF, RDFS, Namespace, URIRef

from backend.graphdb.graphs import CLASSES_AND_ATTRIBUTES_GRAPH, ONTOLOGY_GRAPH
from backend.replica_builder.utils.ttl_attribute_helpers import generate_attribute_ttl
from backend.scenario_builder.graph_lookups import categorical_values

D = Namespace("https://digicities.info/ontology#")
P = "https://x.org/p"
PREFIXES = "@prefix dici_onto: <https://digicities.info/ontology#> .\n"


def test_the_replica_writer_states_the_category_iri():
    attr = f"{P}/Building/B1/BuildingType"
    lines = generate_attribute_ttl(attr, "BuildingType",
                                   {"type": "Categorical", "category_value": "MFH"}, "Building")
    g = rdflib.Graph().parse(data=PREFIXES + "\n".join(lines), format="turtle")
    node = URIRef(attr)
    assert (node, D.hasCategoricalValue, D.MFH) in g
    assert (node, RDF.type, D.MFH) not in g
    assert (node, RDF.type, D.CategoricalAttribute) in g


class _Store:
    def __init__(self, ontology: rdflib.Graph, data: rdflib.Graph):
        self.ds = rdflib.Dataset()
        self.ds.graph(URIRef(ONTOLOGY_GRAPH)).__iadd__(ontology)
        self.ds.graph(URIRef(CLASSES_AND_ATTRIBUTES_GRAPH)).__iadd__(data)

    def sparql_api_query(self, query: str, out_format: str = "df") -> pd.DataFrame:
        res = self.ds.query(query)
        return pd.DataFrame([[str(v) for v in row] for row in res],
                            columns=[str(v) for v in res.vars])


def _schema() -> rdflib.Graph:
    g = rdflib.Graph()
    g.add((D.BuildingType, RDFS.subClassOf, D.CategoricalAttribute))
    for value in (D.MFH, D.SFH):
        g.add((value, RDF.type, D.BuildingType))
    return g


def test_categorical_values_reads_the_stated_value_and_old_data():
    data = rdflib.Graph()
    new, old = URIRef(f"{P}/B1/BuildingType"), URIRef(f"{P}/B2/BuildingType")
    data.add((new, RDF.type, D.BuildingType))
    data.add((new, D.hasCategoricalValue, D.MFH))
    data.add((old, RDF.type, D.BuildingType))
    data.add((old, RDF.type, D.SFH))            # written before the property was stated
    found = categorical_values(_Store(_schema(), data))
    assert found == {str(new): str(D.MFH), str(old): str(D.SFH)}
