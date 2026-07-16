# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Ontology-schema queries (the ``<ontology_dici_onto>`` named graph).

Pure, UI-independent reads of the ontology schema: component / attribute classes
and their constraints, link properties, categorical named individuals, units, and
ratio units. Each takes a client and returns a pandas DataFrame. The graph IRI
comes from ``backend.graphdb.graphs`` (single source of truth).

Used by the Replica Builder (ontology loader, link manager). Queries scope the
ontology graph with an explicit ``GRAPH <...>`` clause, which is portable across
triple stores.
"""

from __future__ import annotations

import pandas as pd

from backend.graphdb.graphs import ONTOLOGY_GRAPH
from backend.graphdb.queries._exec import run_df

_PREFIXES = (
    "PREFIX dici_onto: <https://digicities.info/ontology#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
    "PREFIX qudt: <http://qudt.org/schema/qudt/>\n"
    "PREFIX unit: <http://qudt.org/vocab/unit/>\n"
)
_G = f"<{ONTOLOGY_GRAPH}>"


def get_link_properties(client) -> pd.DataFrame:
    """linksComponent subproperties (excluding linksComponent). Columns: property, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?property ?label
    WHERE {{
        GRAPH {_G} {{
            ?property rdfs:subPropertyOf* dici_onto:linksComponent .
            OPTIONAL {{ ?property rdfs:label ?label }}
        }}
        FILTER(?property != dici_onto:linksComponent)
    }}
    ORDER BY ?property
    """
    return run_df(client, query, ["property", "label"])


def get_components(client) -> pd.DataFrame:
    """Component classes (subclasses of Component, excluding it). Columns: class, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?class ?label
    WHERE {{
        GRAPH {_G} {{
            ?class rdfs:subClassOf* dici_onto:Component .
            OPTIONAL {{ ?class rdfs:label ?label }}
        }}
        FILTER(?class != dici_onto:Component)
        FILTER(?class != owl:Nothing)
    }}
    ORDER BY ?class
    """
    return run_df(client, query, ["class", "label"])


def get_attributes_with_constraints(client) -> pd.DataFrame:
    """Attribute classes with default unit / quantity kind / type hierarchy.

    Columns: class, label, defaultUnit, quantityKind, attrType.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?class ?label ?defaultUnit ?quantityKind ?attrType
    WHERE {{
        GRAPH {_G} {{
            ?class rdfs:subClassOf* dici_onto:Attribute .
            OPTIONAL {{ ?class rdfs:label ?label }}
            OPTIONAL {{ ?class dici_onto:hasDefaultUnit ?defaultUnit }}
            OPTIONAL {{ ?class dici_onto:hasQuantityKind ?quantityKind }}
            OPTIONAL {{
                ?class rdfs:subClassOf* ?attrType .
                FILTER(?attrType IN (
                    dici_onto:PhysicalAttribute,
                    dici_onto:DynamicAttribute,
                    dici_onto:CategoricalAttribute,
                    dici_onto:EventAttribute,
                    dici_onto:CurveAttribute,
                    dici_onto:SimpleCostAttribute,
                    dici_onto:UnitBasedCostAttribute,
                    dici_onto:ResourceAttribute,
                    dici_onto:SimpleValueAttribute,
                    dici_onto:CustomPhysicalRatioAttribute,
                    dici_onto:GeospatialAttribute
                ))
            }}
        }}
        FILTER(?class != dici_onto:Attribute)
        FILTER(?class != owl:Nothing)
    }}
    ORDER BY ?class
    """
    return run_df(client, query, ["class", "label", "defaultUnit", "quantityKind", "attrType"])


def get_component_subclasses(client) -> pd.DataFrame:
    """Component subclasses (excluding Component) for naming-convention mapping.

    Columns: component.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?component
    WHERE {{
        GRAPH {_G} {{
            ?component rdfs:subClassOf* dici_onto:Component .
        }}
        FILTER(?component != dici_onto:Component)
        FILTER(?component != owl:Nothing)
    }}
    ORDER BY ?component
    """
    return run_df(client, query, ["component"])


def get_attribute_subclasses_for(client, attribute_class_name: str) -> pd.DataFrame:
    """Attribute subclasses of a named attribute class (by local name), excluding it.

    Columns: attribute, label.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?attribute ?label
    WHERE {{
        GRAPH {_G} {{
            ?attribute rdfs:subClassOf* dici_onto:{attribute_class_name} .
            OPTIONAL {{ ?attribute rdfs:label ?label }}
        }}
        FILTER(?attribute != dici_onto:{attribute_class_name})
        FILTER(?attribute != owl:Nothing)
    }}
    ORDER BY ?attribute
    """
    return run_df(client, query, ["attribute", "label"])


def get_named_individuals(client) -> pd.DataFrame:
    """Named individuals of categorical attribute classes. Columns: individual, class, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?individual ?class ?label
    WHERE {{
        GRAPH {_G} {{
            ?individual a owl:NamedIndividual .
            ?individual a ?class .
            ?class rdfs:subClassOf* dici_onto:CategoricalAttribute .
            OPTIONAL {{ ?individual rdfs:label ?label }}
        }}
        FILTER(?class != dici_onto:CategoricalAttribute)
    }}
    ORDER BY ?class ?individual
    """
    return run_df(client, query, ["individual", "class", "label"])


def get_default_units(client) -> pd.DataFrame:
    """Units referenced via hasDefaultUnit in the ontology. Columns: unit, label."""
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?unit ?label
    WHERE {{
        GRAPH {_G} {{
            ?something dici_onto:hasDefaultUnit ?unit .
        }}
    }}
    ORDER BY ?unit
    """
    return run_df(client, query, ["unit", "label"])


def get_ratio_units(client) -> pd.DataFrame:
    """hasRatioUnits numerator/denominator units for CustomPhysicalRatio attributes.

    Columns: class, numUnit, denUnit.
    """
    query = f"""
    {_PREFIXES}
    SELECT DISTINCT ?class ?numUnit ?denUnit
    WHERE {{
        GRAPH {_G} {{
            ?class dici_onto:hasRatioUnits ?node .
            ?node dici_onto:numeratorUnit ?numUnit .
            ?node dici_onto:denominatorUnit ?denUnit .
        }}
    }}
    """
    return run_df(client, query, ["class", "numUnit", "denUnit"])
