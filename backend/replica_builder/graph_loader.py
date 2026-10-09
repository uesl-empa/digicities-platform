# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Replica load-back: rdflib graphs → the in-app instance/link model, headless.

The pure parsing half of ``components/replica_builder/replica_graph_loader.py``
(moved verbatim in Phase 5 of the backend/UI split), plus:

* :func:`load_replica_model` — one call that pulls a workspace's current
  replica out of the triplestore (both named graphs + the semantic discovery
  queries) and returns ``(instances, links)``.
* :func:`parse_local_replica_graph` — the same parse-back for a *standalone*
  generated TTL (no triplestore, no ontology): discovery falls back to the
  asserted structure the platform's own generators emit (``hasAttribute``
  links, asserted kind classes). This is what lets the Excel importer reuse
  ``process_excel_to_ttl`` as the single workbook parser and read the session
  model back out of its TTL.

``parse_links_from_graph`` takes the instance list explicitly (the Streamlit
shim passes ``st.session_state.replica_instances``).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import DCTERMS

from backend.ontology_kinds import (
    KIND_CLASS, AttributeKind, core_graph, dici_local_name, in_namespace,
    is_attribute_class, is_attribute_predicate, is_subclass_of, kind_for_class,
    kind_of_node,
)
from backend.replica_builder.model import ComponentInstance

DICI = Namespace("https://digicities.info/ontology#")
QUDT_NS = Namespace("http://qudt.org/schema/qudt/")
UNIT_NS = Namespace("http://qudt.org/vocab/unit/")


def local_name(uri: str) -> str:
    """Local name of a URI (after '#', else after the last '/')."""
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


# Kept for the shim's old private spelling.
_local_name = local_name


def schema_view(graph: Graph, ontology: Optional[Graph] = None) -> Graph:
    """``graph`` plus the core ontology, and the workspace ontology (core +
    extensions) when given, as one read-only graph. Every "what is this"
    question below is asked of this view, through the class and property
    hierarchy."""
    parts = [graph] + ([ontology] if ontology is not None else []) + [core_graph()]
    return ReadOnlyGraphAggregate(parts)


def _class_objects(schema: Graph, subject: URIRef, attribute_nodes) -> Dict[str, str]:
    """An instance's ``dici_onto:`` object links that are not attribute links:
    neither an ``rdfs:subPropertyOf* dici_onto:hasAttribute`` predicate nor
    pointing at a known attribute node (minted ``has<Sheet><Name>Attribute``
    predicates are not declared, but their objects are attribute nodes)."""
    out: Dict[str, str] = {}
    for p, o in schema.predicate_objects(subject):
        name = dici_local_name(p)
        if name is None or not isinstance(o, URIRef):
            continue
        if o in attribute_nodes or is_attribute_predicate(schema, p):
            continue
        out[name] = str(o)
    return out


def parse_instances_from_graph(graph: Graph, discovered, attr_links=None,
                               ontology: Optional[Graph] = None) -> List[Dict[str, Any]]:
    """Build instance dicts from the semantically-discovered (instance, type,
    label) rows returned by ``components.get_all_component_instances`` (which uses
    ``rdfs:subClassOf* dici_onto:Component`` against the ontology). The constructed
    ``graph`` is used only to read each instance's annotations and class-object
    links — literal/relationship data, not ontology classification.

    ``attr_links`` (the ``get_all_instance_attribute_links`` rows) and
    ``ontology`` (the workspace ontology graph) keep attribute links out of the
    class objects; without them only the core hierarchy is consulted.
    """
    instances = []
    if discovered is None or getattr(discovered, "empty", True):
        return instances
    schema = schema_view(graph, ontology)
    attribute_nodes = set()
    if attr_links is not None and not getattr(attr_links, "empty", True):
        attribute_nodes = {URIRef(str(a)) for a in attr_links["attribute"]}

    for _, row in discovered.iterrows():
        uri = row["instance"]
        component_uri = URIRef(uri)
        label = row["label"] if isinstance(row.get("label"), str) and row["label"] else local_name(uri)

        instance_data = {
            'uri': uri,
            'type': local_name(str(row["type"])),
            'label': label,
            'annotations': {},
            'class_objects': {},
        }

        # Annotations: rdfs:* properties other than label (literal data).
        for p, o in graph.predicate_objects(component_uri):
            pred_str = str(p)
            if pred_str.startswith(str(RDFS)) and pred_str != str(RDFS.label):
                instance_data['annotations'][pred_str.replace(str(RDFS), "")] = str(o)

        # Class-object relationships: dici_onto object links that are not
        # attribute links (decided by the property hierarchy).
        instance_data['class_objects'] = _class_objects(schema, component_uri, attribute_nodes)

        instances.append(instance_data)

    return instances


def _kind_map(attr_kinds) -> Dict[str, str]:
    """Build {attribute_uri: editor_kind} from get_attribute_kinds() rows.

    Each row's kind class IRI maps to its ``AttributeKind`` by exact IRI; the
    kind's tag ("Physical", "SimpleCost", ...) is what parse_single_attribute's
    value-extraction branches expect. An attribute under several kind classes
    gets the first one in ``KIND_CLASS`` order.
    """
    if attr_kinds is None or getattr(attr_kinds, "empty", True):
        return {}
    rank = {kind: i for i, kind in enumerate(KIND_CLASS)}
    best: Dict[str, AttributeKind] = {}
    for _, row in attr_kinds.iterrows():
        kind = kind_for_class(URIRef(str(row["kind"])))
        if kind is None:
            continue
        attr = str(row["attribute"])
        if attr not in best or rank[kind] < rank[best[attr]]:
            best[attr] = kind
    return {attr: kind.value for attr, kind in best.items()}


def parse_attributes_from_graph(graph: Graph, attr_links, attr_kinds=None,
                                ontology: Optional[Graph] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Group attribute values by instance, keyed on the instance→attribute links
    discovered semantically via ``rdfs:subPropertyOf* dici_onto:hasAttribute``
    (``components.get_all_instance_attribute_links``). Each attribute's editor
    kind comes from ``components.get_attribute_kinds`` (``rdfs:subClassOf*`` onto a
    kind class). The constructed ``graph`` supplies the literal values only;
    ``ontology`` (the workspace ontology graph) lets extension attribute classes
    be told apart from category values.
    """
    attributes_by_instance: Dict[str, List[Dict[str, Any]]] = {}
    if attr_links is None or getattr(attr_links, "empty", True):
        return attributes_by_instance

    kind_by_attr = _kind_map(attr_kinds)
    schema = schema_view(graph, ontology)

    for _, row in attr_links.iterrows():
        instance_uri = row["instance"]
        attr_uri = row["attribute"]
        attr_data = parse_single_attribute(
            graph, URIRef(attr_uri), QUDT_NS, UNIT_NS,
            attr_type=kind_by_attr.get(str(attr_uri)), schema=schema,
        )
        if attr_data:
            attributes_by_instance.setdefault(instance_uri, []).append(attr_data)

    return attributes_by_instance


def parse_single_attribute(graph: Graph, attr_uri, QUDT_NS=QUDT_NS, UNIT_NS=UNIT_NS,
                           attr_type: Optional[str] = None,
                           schema: Optional[Graph] = None) -> Optional[Dict[str, Any]]:
    """Parse a single attribute instance from the graph.

    ``attr_type`` is the editor kind ("Physical", "Categorical", …) resolved
    semantically via ``components.get_attribute_kinds`` (``rdfs:subClassOf*`` onto a
    kind class). When not supplied — e.g. a direct call without the ontology — it
    falls back to the attribute node's types in ``schema`` (default: ``graph``
    plus the core ontology), again through ``rdfs:subClassOf*``. Either way the
    value extraction below is driven by the kind, never by class-name spelling.
    """
    if schema is None:
        schema = schema_view(graph)

    # Extract attribute name from URI (last segment after /)
    # URI structure: .../ComponentInstance/AttributeName
    attr_name = str(attr_uri).split('/')[-1]

    # Fallback kind detection (only when the semantic kind wasn't passed in):
    # the node's types, through the class hierarchy.
    kind = AttributeKind(attr_type) if attr_type else kind_of_node(schema, URIRef(attr_uri))

    if not attr_name:
        return None  # Can't identify the attribute

    # Default to Physical if the kind couldn't be determined.
    if kind is None:
        kind = AttributeKind.PHYSICAL
    attr_type = kind.value

    # Build attribute data dict
    attr_data = {
        'type': attr_type,
        'name': attr_name
    }

    # Extract values based on attribute type
    if kind in (AttributeKind.PHYSICAL, AttributeKind.DYNAMIC):
        # Get value
        for value in graph.objects(attr_uri, QUDT_NS.value):
            attr_data['value'] = str(value)
            break

        # Get unit
        for unit_uri in graph.objects(attr_uri, QUDT_NS.unit):
            unit_str = str(unit_uri)
            if '/unit/' in unit_str:
                attr_data['unit'] = unit_str.split('/unit/')[-1]
            break

        # Get datasource
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)
            break

        # Check for time series references
        for ts_ref in graph.objects(attr_uri, DICI.hasHistoricTimeSeriesReference):
            attr_data['historic_reference'] = str(ts_ref)
        for ts_ref in graph.objects(attr_uri, DICI.hasFutureTimeSeriesReference):
            attr_data['future_reference'] = str(ts_ref)
        for ts_ref in graph.objects(attr_uri, DICI.hasLiveTimeSeriesReference):
            attr_data['live_reference'] = str(ts_ref)

    elif kind is AttributeKind.CATEGORICAL:
        # The category is the node's dici_onto:hasCategoricalValue when stated.
        # Otherwise it is encoded as a dici_onto rdf:type of the attribute node
        # (e.g. <.../BuildingType> a dici_onto:MFH): the one type the hierarchy
        # does not place under dici_onto:Attribute (other namespaces, such as
        # the inferred rdfs:Resource / owl:Thing, are never a category). When
        # the schema does not know the attribute's own class, two types remain
        # and no value is guessed.
        stated = next(iter(graph.objects(attr_uri, DICI.hasCategoricalValue)), None)
        if stated is not None:
            attr_data['category_value'] = dici_local_name(stated) or str(stated)
        else:
            candidates = [n for t in graph.objects(attr_uri, RDF.type)
                          if (n := dici_local_name(t)) is not None
                          and not is_attribute_class(schema, t)]
            if len(candidates) == 1:
                attr_data['category_value'] = candidates[0]

    elif kind is AttributeKind.EVENT:
        # Get temporal value and precision
        for temp_val in graph.objects(attr_uri, DICI.hasTemporalValue):
            attr_data['temporal_value'] = str(temp_val)
        for precision in graph.objects(attr_uri, DICI.hasTemporalPrecision):
            prec_str = dici_local_name(precision) or str(precision)
            attr_data['temporal_precision'] = prec_str
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif kind in (AttributeKind.SIMPLE_COST, AttributeKind.UNIT_BASED_COST):
        # Get value
        for value in graph.objects(attr_uri, QUDT_NS.value):
            attr_data['value'] = str(value)

        # Get unit (for UnitBasedCost)
        for unit_uri in graph.objects(attr_uri, QUDT_NS.unit):
            unit_str = str(unit_uri)
            if '/unit/' in unit_str:
                attr_data['unit'] = unit_str.split('/unit/')[-1]

        # Get currency
        for curr in graph.objects(attr_uri, DICI.currency):
            curr_str = str(curr)
            if 'currency/' in curr_str:
                attr_data['currency'] = curr_str.split('currency/')[-1]

        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif kind is AttributeKind.RESOURCE:
        # Get data path
        for data_path in graph.objects(attr_uri, DICI.hasDataPath):
            attr_data['data_path'] = str(data_path)

    elif kind is AttributeKind.SIMPLE_VALUE:
        # Get attribute value
        for value in graph.objects(attr_uri, DICI.hasAttributeValue):
            attr_data['value'] = str(value)
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif kind is AttributeKind.CUSTOM_PHYSICAL_RATIO:
        # Get value and custom unit
        for value in graph.objects(attr_uri, QUDT_NS.value):
            attr_data['value'] = str(value)
        for unit in graph.objects(attr_uri, QUDT_NS.unit):
            attr_data['custom_unit'] = str(unit)
        if 'custom_unit' not in attr_data:
            # Ratio units have no single QUDT IRI — both generators write the
            # ratio string via dici_onto:hasUnitLabel ("Num/Den"), so read that
            # when no qudt:unit triple exists.
            for unit_label in graph.objects(attr_uri, DICI.hasUnitLabel):
                attr_data['custom_unit'] = str(unit_label)
                break
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif kind is AttributeKind.CURVE:
        # Units come as unit: IRIs (xUnit/yUnit) with string labels alongside.
        for x_unit in graph.objects(attr_uri, DICI.xUnit):
            attr_data['x_unit'] = local_name(str(x_unit))
            break
        for y_unit in graph.objects(attr_uri, DICI.yUnit):
            attr_data['y_unit'] = local_name(str(y_unit))
            break
        for points in graph.objects(attr_uri, DICI.hasDataPoints):
            attr_data['data_points'] = _curve_points_to_editor_format(str(points))
            break
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif kind is AttributeKind.IDENTIFIER:
        for ident in graph.objects(attr_uri, DICI.identifierValue):
            attr_data['identifier_value'] = str(ident)
            break

    elif kind is AttributeKind.GEOSPATIAL:
        # Get geospatial value
        for value in graph.objects(attr_uri, DICI.hasAttributeValue):
            attr_data['value'] = str(value)
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    return attr_data


def _curve_points_to_editor_format(stored: str) -> str:
    """Rebuild the editor's ``[(x1,y1);(x2,y2)]`` curve string from the stored
    pretty-printed ``[[x, y], …]`` literal both TTL generators emit."""
    pairs = re.findall(r"\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]", stored)
    if not pairs:
        return stored
    return "[" + ";".join(f"({x},{y})" for x, y in pairs) + "]"


def convert_to_replica_instances(instances: List[Dict[str, Any]],
                                 attributes: Dict[str, List[Dict[str, Any]]]) -> List[ComponentInstance]:
    """Convert parsed graph data to replica builder instance format"""
    replica_instances = []
    seen_uris = set()

    for instance in instances:
        # Extract instance ID from URI
        instance_uri = instance['uri']
        # An instance can appear more than once (e.g. dual-typed). Build it once.
        if instance_uri in seen_uris:
            continue
        seen_uris.add(instance_uri)
        instance_id = instance_uri.split('/')[-1]

        # Create ComponentInstance object (not a dict!)
        component_instance = ComponentInstance(
            id=instance_id,
            component_type=instance['type'],
            uri=instance_uri,
            label=instance.get('label', instance_id),
            attributes={},  # Will populate below
            annotations=instance.get('annotations', {}),
            class_objects=instance.get('class_objects', {})
        )

        # Add attributes if they exist. Copy (don't pop) so the shared attribute
        # dicts aren't mutated — popping breaks any reuse of the same list.
        if instance_uri in attributes:
            for attr_data in attributes[instance_uri]:
                attr_name = attr_data.get('name')
                if not attr_name:
                    continue
                component_instance.attributes[attr_name] = {
                    k: v for k, v in attr_data.items() if k != 'name'
                }

        replica_instances.append(component_instance)

    return replica_instances


def parse_links_from_graph(graph: Graph,
                           instances: List[ComponentInstance]) -> List[Dict[str, Any]]:
    """Parse links from system_description graph, resolved against ``instances``."""
    links = []

    # First, create maps by both ID and URI for instance lookups
    instances_by_id = {}
    instances_by_uri = {}
    for inst in instances:
        instances_by_id[inst.id] = inst
        instances_by_uri[inst.uri] = inst

    schema = schema_view(graph)

    # Find all triples in the system_description graph
    for s, p, o in graph:
        source_uri = str(s)
        pred_str = str(p)
        target_uri = str(o)

        # A dici_onto predicate between two known instances is a link, unless
        # the property hierarchy says it attaches an attribute.
        property_name = dici_local_name(p)
        if property_name is not None:

            if is_attribute_predicate(schema, p):
                continue

            # Try to find instances by URI first (most reliable)
            source_inst = instances_by_uri.get(source_uri)
            target_inst = instances_by_uri.get(target_uri)

            # If not found by URI, try extracting ID from URI
            if not source_inst:
                source_id = source_uri.split('/')[-1]
                source_inst = instances_by_id.get(source_id)

            if not target_inst:
                target_id = target_uri.split('/')[-1]
                target_inst = instances_by_id.get(target_id)

            # Only create link if both instances exist
            if source_inst and target_inst:
                links.append({
                    'source_id': source_inst.id,
                    'target_id': target_inst.id,
                    'source_uri': source_inst.uri,
                    'target_uri': target_inst.uri,
                    'source_type': source_inst.component_type,
                    'target_type': target_inst.component_type,
                    'property': property_name,
                    'source_label': source_inst.label,
                    'target_label': target_inst.label
                })

    return links


# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------

def load_replica_model(client) -> Tuple[List[ComponentInstance], List[Dict[str, Any]]]:
    """The workspace's current replica out of the triplestore: both named graphs
    constructed, instances/attributes discovered semantically (SPARQL over the
    ontology hierarchy), links resolved against the recovered instances.

    Returns ``(instances, links)``; either may be empty when the graphs are.
    """
    from backend.graphdb.graphs import (
        CLASSES_AND_ATTRIBUTES_GRAPH,
        ONTOLOGY_GRAPH,
        SYSTEM_DESCRIPTION_GRAPH,
    )
    from backend.graphdb.queries import graph_io
    from backend.graphdb.queries import components as components_q

    instances: List[ComponentInstance] = []
    links: List[Dict[str, Any]] = []

    classes_graph = graph_io.construct_named_graph(client, CLASSES_AND_ATTRIBUTES_GRAPH)
    if classes_graph is not None:
        ontology = graph_io.construct_named_graph(client, ONTOLOGY_GRAPH)
        discovered = components_q.get_all_component_instances(client)
        attr_links = components_q.get_all_instance_attribute_links(client)
        attr_kinds = components_q.get_attribute_kinds(client)
        parsed = parse_instances_from_graph(classes_graph, discovered, attr_links, ontology)
        attributes = parse_attributes_from_graph(classes_graph, attr_links, attr_kinds, ontology)
        instances = convert_to_replica_instances(parsed, attributes)

    system_graph = graph_io.construct_named_graph(client, SYSTEM_DESCRIPTION_GRAPH)
    if system_graph is not None and instances:
        links = parse_links_from_graph(system_graph, instances)

    return instances, links


def parse_local_replica_graph(graph: Graph,
                              project_uri: Optional[str] = None,
                              ontology: Optional[Graph] = None) -> List[ComponentInstance]:
    """Parse a *standalone* classes_and_attributes graph (e.g. the TTL just
    written by ``process_excel_to_ttl``) into ComponentInstances — no
    triplestore, no ontology.

    Discovery leans on the asserted structure the platform's generators emit,
    read through the core ontology's hierarchy:

    * attribute nodes are objects of an ``rdfs:subPropertyOf*
      dici_onto:hasAttribute`` predicate (``hasAttribute`` and ``hasIdentifier``
      included; the generator writes ``hasAttribute`` next to every minted
      ``has<Sheet><Name>Attribute``, which is not declared anywhere);
    * component instances are the remaining subjects with a ``dici_onto:``
      rdf:type, excluding time-series and reference nodes (types under
      ``dici_onto:TimeSeries`` / ``dici_onto:Reference``);
    * attribute kinds come from each node's types through ``rdfs:subClassOf*``
      (``parse_single_attribute``'s fallback path).

    ``project_uri`` additionally recovers free-form Annotation columns the
    Excel converter writes into the project namespace (``:<name> "value"``).
    ``ontology`` is the workspace schema: it tells an attribute's own class
    from the category it holds when the data does not state
    ``dici_onto:hasCategoricalValue``.
    """
    dici = str(DICI)
    schema = schema_view(graph, ontology)

    # 1. Attribute + identifier nodes (never instances).
    attribute_predicates = {p for p in set(graph.predicates())
                            if is_attribute_predicate(schema, p)}
    attr_nodes = set()
    attr_links: Dict[URIRef, List[URIRef]] = {}
    for s, p, o in graph:
        if p in attribute_predicates and isinstance(o, URIRef):
            attr_nodes.add(o)
            attr_links.setdefault(s, [])
            if o not in attr_links[s]:
                attr_links[s].append(o)

    identifier_nodes = set(graph.objects(None, DICI.hasIdentifier))

    # 2. Structural types to skip: time series and references.
    structural_types = {
        t for t in set(graph.objects(None, RDF.type))
        if is_subclass_of(schema, t, DICI.TimeSeries) or is_subclass_of(schema, t, DICI.Reference)
    }
    structural_nodes = {s for t in structural_types for s in graph.subjects(RDF.type, t)}

    # 3. Component instances: subjects with a dici_onto: type that aren't
    # attribute / time-series / reference nodes.
    instance_types: Dict[URIRef, str] = {}
    for s, o in graph.subject_objects(RDF.type):
        if not isinstance(s, URIRef) or not isinstance(o, URIRef):
            continue
        if s in attr_nodes or s in structural_nodes:
            continue
        type_name = dici_local_name(o)
        if type_name is None:
            continue
        # Deterministic when (rarely) multi-typed.
        if s not in instance_types or type_name < instance_types[s]:
            instance_types[s] = type_name

    project_ns = f"{project_uri}#" if project_uri else None

    instances: List[ComponentInstance] = []
    for subject in sorted(instance_types, key=str):
        uri = str(subject)
        type_name = instance_types[subject]

        label = None
        for lbl in graph.objects(subject, RDFS.label):
            label = str(lbl)
            break

        annotations: Dict[str, str] = {}
        for p, o in graph.predicate_objects(subject):
            pred_str = str(p)
            if in_namespace(p, RDFS) and p != RDFS.label:
                annotations[pred_str[len(str(RDFS)):]] = str(o)
            elif project_ns and in_namespace(p, project_ns) and isinstance(o, Literal):
                # Free-form Annotation columns land in the project namespace.
                annotations[pred_str[len(project_ns):]] = str(o)
        class_objects = _class_objects(schema, subject, attr_nodes)

        instance = ComponentInstance(
            id=uri.split('#')[-1] if '#' in uri else uri.split('/')[-1],
            component_type=type_name,
            uri=uri,
            label=label or (uri.split('#')[-1] if '#' in uri else uri.split('/')[-1]),
            annotations=annotations,
            class_objects=class_objects,
        )

        for attr_uri in attr_links.get(subject, []):
            forced_kind = AttributeKind.IDENTIFIER.value if attr_uri in identifier_nodes else None
            attr_data = parse_single_attribute(graph, attr_uri, attr_type=forced_kind, schema=schema)
            if attr_data and attr_data.get('name'):
                name = attr_data.pop('name')
                instance.attributes[name] = attr_data

        instances.append(instance)

    return instances


__all__ = [
    "DICI",
    "QUDT_NS",
    "UNIT_NS",
    "local_name",
    "parse_instances_from_graph",
    "parse_attributes_from_graph",
    "parse_single_attribute",
    "convert_to_replica_instances",
    "parse_links_from_graph",
    "load_replica_model",
    "parse_local_replica_graph",
]
