# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Component/attribute discovery for the Service Requirements Builder.

Two sources feed the builder's palette: an uploaded ontology file (parsed
here with rdflib) and the workspace triplestore (queried through
``backend.graphdb.queries`` — the SPARQL lives there, not here). Both produce
the same shape: dicts of :class:`~backend.service_requirements.models
.ComponentClass` / ``AttributeClass`` keyed by local name.

Headless by design. Progress and problems are reported through an optional
``on_status(level, message)`` callback (levels ``"success"``, ``"info"``,
``"warning"``, ``"error"``); the Streamlit shim maps them onto
``st.success`` / ``st.info`` / ``st.warning`` / ``st.error``.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from backend.graphdb import queries as gdb_queries
from backend.service_requirements.models import AttributeClass, ComponentClass

try:
    from rdflib import Graph, Namespace
    from rdflib.namespace import RDFS

    RDFLIB_AVAILABLE = True
    DICI_ONTO = Namespace("https://digicities.info/ontology#")
except ImportError:  # pragma: no cover - rdflib is a hard dependency in practice
    RDFLIB_AVAILABLE = False
    DICI_ONTO = None

StatusCallback = Optional[Callable[[str, str], None]]


def _notify(on_status: StatusCallback, level: str, message: str) -> None:
    if on_status is not None:
        on_status(level, message)


def extract_local_name(uri: str) -> str:
    """The local name of a URI: the part after '#', else after the last '/'."""
    if '#' in uri:
        return uri.split('#')[-1]
    elif '/' in uri:
        return uri.split('/')[-1]
    return uri


# SPARQL run over the *uploaded file's* in-memory rdflib graph — not against
# the triplestore (those queries live in backend.graphdb.queries).
_FILE_COMPONENT_QUERY = """
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?class ?label WHERE {
    ?class rdfs:subClassOf* dici_onto:Component .
    OPTIONAL { ?class rdfs:label ?label }
}
"""

_FILE_ATTRIBUTE_QUERY = """
PREFIX dici_onto: <https://digicities.info/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?class ?label WHERE {
    {
        ?class rdfs:subClassOf* dici_onto:StaticAttribute .
    }
    UNION
    {
        ?class rdfs:subClassOf* dici_onto:DynamicAttribute .
    }
    OPTIONAL { ?class rdfs:label ?label }
}
"""


def parse_ontology_content(
    file_content, on_status: StatusCallback = None,
) -> Tuple[Dict[str, ComponentClass], Dict[str, AttributeClass]]:
    """Parse ontology file content (bytes or str) into component/attribute dicts.

    Tries Turtle, then RDF/XML, then N3. Component classes are everything
    ``rdfs:subClassOf* dici_onto:Component``; attribute classes are the
    Static/DynamicAttribute subtrees. When the in-memory SPARQL fails, falls
    back to scanning direct ``subClassOf Component`` triples.
    """
    if not RDFLIB_AVAILABLE:
        _notify(on_status, 'error', "rdflib is not installed. Cannot parse ontology file.")
        return {}, {}

    try:
        g = Graph()

        try:
            g.parse(data=file_content, format='turtle')
        except Exception:
            try:
                g.parse(data=file_content, format='xml')
            except Exception:
                try:
                    g.parse(data=file_content, format='n3')
                except Exception as e:
                    _notify(on_status, 'error', f"Could not parse ontology file: {e}")
                    return {}, {}

        components: Dict[str, ComponentClass] = {}
        attributes: Dict[str, AttributeClass] = {}

        try:
            for row in g.query(_FILE_COMPONENT_QUERY):
                class_uri = str(row.class_)
                class_name = extract_local_name(class_uri)
                label = str(row.label) if row.label else class_name

                components[class_name] = ComponentClass(
                    uri=class_uri,
                    label=label,
                    parent_classes=[],
                    attributes=[]
                )

            for row in g.query(_FILE_ATTRIBUTE_QUERY):
                attr_uri = str(row.class_)
                attr_name = extract_local_name(attr_uri)
                label = str(row.label) if row.label else attr_name

                attributes[attr_name] = AttributeClass(
                    uri=attr_uri,
                    label=label,
                    domain="",
                    range_type="string"
                )

        except Exception as e:
            _notify(on_status, 'warning',
                    f"SPARQL queries failed, falling back to basic RDF parsing: {e}")

            for subj, pred, obj in g:
                if pred == RDFS.subClassOf and obj == DICI_ONTO.Component:
                    class_name = extract_local_name(str(subj))
                    components[class_name] = ComponentClass(
                        uri=str(subj),
                        label=class_name,
                        parent_classes=[],
                        attributes=[]
                    )

        _notify(on_status, 'success',
                f"Parsed ontology: {len(components)} components, {len(attributes)} attributes")
        return components, attributes

    except Exception as e:
        _notify(on_status, 'error', f"Error parsing ontology file: {e}")
        return {}, {}


def load_components_and_attributes(
    client, on_status: StatusCallback = None,
) -> Tuple[Dict[str, ComponentClass], Dict[str, AttributeClass]]:
    """All component and attribute classes from the triplestore."""
    if not client:
        _notify(on_status, 'warning', "No Triplestore client available")
        return {}, {}

    components: Dict[str, ComponentClass] = {}
    attributes: Dict[str, AttributeClass] = {}

    try:
        comp_df = gdb_queries.get_component_classes(client)
        for _, row in comp_df.iterrows():
            class_uri = row['class']
            class_name = extract_local_name(class_uri)
            label = row.get('label', class_name) if pd.notna(row.get('label')) else class_name

            components[class_name] = ComponentClass(
                uri=class_uri,
                label=label,
                parent_classes=[],
                attributes=[]
            )

        attr_df = gdb_queries.get_attribute_classes(client)
        for _, row in attr_df.iterrows():
            attr_uri = row['class']
            attr_name = extract_local_name(attr_uri)
            label = row.get('label', attr_name) if pd.notna(row.get('label')) else attr_name

            attributes[attr_name] = AttributeClass(
                uri=attr_uri,
                label=label,
                domain="",
                range_type="string"
            )

        _notify(on_status, 'success',
                f"Retrieved from Triplestore: {len(components)} components, "
                f"{len(attributes)} attributes")
        return components, attributes

    except Exception as e:
        _notify(on_status, 'error', f"Error querying Triplestore for components: {e}")
        return {}, {}


def load_attribute_mappings_by_convention(
    client, on_status: StatusCallback = None,
) -> Dict[str, List[str]]:
    """Component -> attribute-name mappings via the naming convention.

    For each component class ``<Name>`` the ontology groups its attributes
    under an abstract ``<Name>Attribute`` class; its subclasses are the valid
    attributes. Every component gets at least ``label``.
    """
    if not client:
        return {}

    try:
        components_result = gdb_queries.get_component_subclasses(client)

        if components_result is None or components_result.empty:
            _notify(on_status, 'warning', "No components found in Triplestore")
            return {}

        component_attributes: Dict[str, List[str]] = {}

        for _, row in components_result.iterrows():
            component_uri = row['component']
            component_name = extract_local_name(component_uri)

            attribute_class_name = f"{component_name}Attribute"

            try:
                attributes_result = gdb_queries.get_attribute_subclasses_for(
                    client, attribute_class_name)

                if attributes_result is not None and not attributes_result.empty:
                    component_attributes[component_name] = []

                    for _, attr_row in attributes_result.iterrows():
                        attr_uri = attr_row['attribute']
                        attr_name = extract_local_name(attr_uri)

                        if attr_name not in component_attributes[component_name]:
                            component_attributes[component_name].append(attr_name)

                    if 'label' not in component_attributes[component_name]:
                        component_attributes[component_name].insert(0, 'label')

                else:
                    component_attributes[component_name] = ['label']

            except Exception as attr_e:
                _notify(on_status, 'warning',
                        f"Could not find attributes for {component_name}: {attr_e}")
                component_attributes[component_name] = ['label']
                continue

        _notify(on_status, 'success',
                f"Retrieved component-attribute mappings for "
                f"{len(component_attributes)} components using naming convention")
        return component_attributes

    except Exception as e:
        _notify(on_status, 'error', f"Error querying Triplestore with new method: {e}")
        return {}


def load_attribute_mappings(
    client, on_status: StatusCallback = None,
) -> Dict[str, List[str]]:
    """Component -> attribute-name mappings, naming convention first.

    Falls back to object-property discovery (``rdfs:domain``/``range`` pairs)
    when the convention finds nothing.
    """
    if not client:
        return {}

    component_attributes = load_attribute_mappings_by_convention(client, on_status)

    if component_attributes:
        return component_attributes

    _notify(on_status, 'info', "Falling back to original object property method...")

    try:
        result = gdb_queries.get_component_attribute_object_properties(client)

        if result is not None and not result.empty:
            component_attributes = {}

            for _, row in result.iterrows():
                component_uri = row['component']
                attribute_uri = row['attribute']

                component_name = extract_local_name(component_uri)
                attribute_name = extract_local_name(attribute_uri)

                if component_name not in component_attributes:
                    component_attributes[component_name] = []

                if attribute_name not in component_attributes[component_name]:
                    component_attributes[component_name].append(attribute_name)

            _notify(on_status, 'success',
                    f"Retrieved component-attribute mappings for "
                    f"{len(component_attributes)} components (fallback method)")
            return component_attributes
        else:
            _notify(on_status, 'info', "No component-attribute mappings found in Triplestore")
            return {}

    except Exception as e:
        _notify(on_status, 'error', f"Error querying Triplestore: {e}")
        return {}
