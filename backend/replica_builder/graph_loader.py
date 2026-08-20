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
from rdflib.namespace import DCTERMS

from backend.replica_builder.model import ComponentInstance

DICI = Namespace("https://digicities.info/ontology#")
QUDT_NS = Namespace("http://qudt.org/schema/qudt/")
UNIT_NS = Namespace("http://qudt.org/vocab/unit/")


def local_name(uri: str) -> str:
    """Local name of a URI (after '#', else after the last '/')."""
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


# Kept for the shim's old private spelling.
_local_name = local_name


def parse_instances_from_graph(graph: Graph, discovered) -> List[Dict[str, Any]]:
    """Build instance dicts from the semantically-discovered (instance, type,
    label) rows returned by ``components.get_all_component_instances`` (which uses
    ``rdfs:subClassOf* dici_onto:Component`` against the ontology). The constructed
    ``graph`` is used only to read each instance's annotations and class-object
    links — literal/relationship data, not ontology classification.
    """
    instances = []
    if discovered is None or getattr(discovered, "empty", True):
        return instances

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

        # Class-object relationships: dici_onto object-predicates (not has*) to URIs.
        excluded_predicates = {'hasAttribute', 'hasIdentifier', 'label'}
        for p, o in graph.predicate_objects(component_uri):
            pred_str = str(p)
            if pred_str.startswith(str(DICI)):
                pred_name = pred_str.replace(str(DICI), "")
                if pred_name not in excluded_predicates and not pred_name.startswith('has') \
                        and isinstance(o, URIRef):
                    instance_data['class_objects'][pred_name] = str(o)

        instances.append(instance_data)

    return instances


def _kind_map(attr_kinds) -> Dict[str, str]:
    """Build {attribute_uri: editor_kind} from get_attribute_kinds() rows.

    The editor kind is the kind class local name minus the ``Attribute`` suffix
    (PhysicalAttribute → "Physical", SimpleCostAttribute → "SimpleCost", …) — the
    form parse_single_attribute's value-extraction branches expect.
    """
    mapping: Dict[str, str] = {}
    if attr_kinds is None or getattr(attr_kinds, "empty", True):
        return mapping
    for _, row in attr_kinds.iterrows():
        kind_local = local_name(str(row["kind"]))
        mapping[str(row["attribute"])] = kind_local[:-len("Attribute")] \
            if kind_local.endswith("Attribute") else kind_local
    return mapping


def parse_attributes_from_graph(graph: Graph, attr_links,
                                attr_kinds=None) -> Dict[str, List[Dict[str, Any]]]:
    """Group attribute values by instance, keyed on the instance→attribute links
    discovered semantically via ``rdfs:subPropertyOf* dici_onto:hasAttribute``
    (``components.get_all_instance_attribute_links``). Each attribute's editor
    kind comes from ``components.get_attribute_kinds`` (``rdfs:subClassOf*`` onto a
    kind class). The constructed ``graph`` supplies the literal values only.
    """
    attributes_by_instance: Dict[str, List[Dict[str, Any]]] = {}
    if attr_links is None or getattr(attr_links, "empty", True):
        return attributes_by_instance

    kind_by_attr = _kind_map(attr_kinds)

    for _, row in attr_links.iterrows():
        instance_uri = row["instance"]
        attr_uri = row["attribute"]
        attr_data = parse_single_attribute(
            graph, URIRef(attr_uri), QUDT_NS, UNIT_NS,
            attr_type=kind_by_attr.get(str(attr_uri)),
        )
        if attr_data:
            attributes_by_instance.setdefault(instance_uri, []).append(attr_data)

    return attributes_by_instance


def parse_single_attribute(graph: Graph, attr_uri, QUDT_NS=QUDT_NS, UNIT_NS=UNIT_NS,
                           attr_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse a single attribute instance from the graph.

    ``attr_type`` is the editor kind ("Physical", "Categorical", …) resolved
    semantically via ``components.get_attribute_kinds`` (``rdfs:subClassOf*`` onto a
    kind class). When not supplied — e.g. a direct call without the ontology — it
    falls back to reading the attribute node's asserted kind class. Either way the
    value extraction below is driven by the kind, never by class-name spelling.
    """

    # Extract attribute name from URI (last segment after /)
    # URI structure: .../ComponentInstance/AttributeName
    attr_name = str(attr_uri).split('/')[-1]

    # Fallback kind detection (only when the semantic kind wasn't passed in):
    # read the attribute node's directly-asserted kind class.
    if not attr_type:
        _kind_classes = {
            'PhysicalAttribute', 'DynamicAttribute', 'CategoricalAttribute',
            'EventAttribute', 'CurveAttribute', 'SimpleCostAttribute',
            'UnitBasedCostAttribute', 'ResourceAttribute', 'SimpleValueAttribute',
            'CustomPhysicalRatioAttribute', 'GeospatialAttribute',
        }
        for type_uri in graph.objects(attr_uri, RDF.type):
            type_str = str(type_uri)
            if type_str.startswith(str(DICI)):
                type_name = type_str.replace(str(DICI), "")
                if type_name in _kind_classes:
                    attr_type = type_name.replace('Attribute', '')
                    break

    if not attr_name:
        return None  # Can't identify the attribute

    # Default to Physical if the kind couldn't be determined.
    if not attr_type:
        attr_type = 'Physical'

    # Build attribute data dict
    attr_data = {
        'type': attr_type,
        'name': attr_name
    }

    # Extract values based on attribute type
    if attr_type in ['Physical', 'Dynamic']:
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

    elif attr_type == 'Categorical':
        # The category value is encoded as a dici_onto rdf:type of the attribute
        # node (e.g. <.../BuildingType> a dici_onto:MFH). Skip structural classes:
        # the attribute's own class, any *Attribute class (CategoricalAttribute and
        # the ComponentAttribute hierarchy), and — via the DICI namespace check —
        # the inferred rdfs:Resource / owl:Thing.
        for type_uri in graph.objects(attr_uri, RDF.type):
            type_str = str(type_uri)
            if type_str.startswith(str(DICI)):
                type_name = type_str.replace(str(DICI), "")
                if type_name != attr_name and not type_name.endswith('Attribute'):
                    attr_data['category_value'] = type_name
                    break

    elif attr_type == 'Event':
        # Get temporal value and precision
        for temp_val in graph.objects(attr_uri, DICI.hasTemporalValue):
            attr_data['temporal_value'] = str(temp_val)
        for precision in graph.objects(attr_uri, DICI.hasTemporalPrecision):
            prec_str = str(precision).replace(str(DICI), "")
            attr_data['temporal_precision'] = prec_str
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif attr_type in ['SimpleCost', 'UnitBasedCost']:
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

    elif attr_type == 'Resource':
        # Get data path
        for data_path in graph.objects(attr_uri, DICI.hasDataPath):
            attr_data['data_path'] = str(data_path)

    elif attr_type == 'SimpleValue':
        # Get attribute value
        for value in graph.objects(attr_uri, DICI.hasAttributeValue):
            attr_data['value'] = str(value)
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif attr_type == 'CustomPhysicalRatio':
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

    elif attr_type == 'Curve':
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

    elif attr_type == 'Identifier':
        for ident in graph.objects(attr_uri, DICI.identifierValue):
            attr_data['identifier_value'] = str(ident)
            break

    elif attr_type == 'Geospatial':
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

    # Find all triples in the system_description graph
    for s, p, o in graph:
        source_uri = str(s)
        pred_str = str(p)
        target_uri = str(o)

        # Check if this is a linking property (from dici_onto namespace)
        # Links are subproperties of linksComponent
        if pred_str.startswith(str(DICI)):
            property_name = pred_str.replace(str(DICI), "")

            # Skip non-linking properties (like rdf:type, rdfs:label, etc.)
            if property_name in ['type', 'label', 'comment', 'hasAttribute']:
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
        SYSTEM_DESCRIPTION_GRAPH,
    )
    from backend.graphdb.queries import graph_io
    from backend.graphdb.queries import components as components_q

    instances: List[ComponentInstance] = []
    links: List[Dict[str, Any]] = []

    classes_graph = graph_io.construct_named_graph(client, CLASSES_AND_ATTRIBUTES_GRAPH)
    if classes_graph is not None:
        discovered = components_q.get_all_component_instances(client)
        attr_links = components_q.get_all_instance_attribute_links(client)
        attr_kinds = components_q.get_attribute_kinds(client)
        parsed = parse_instances_from_graph(classes_graph, discovered)
        attributes = parse_attributes_from_graph(classes_graph, attr_links, attr_kinds)
        instances = convert_to_replica_instances(parsed, attributes)

    system_graph = graph_io.construct_named_graph(client, SYSTEM_DESCRIPTION_GRAPH)
    if system_graph is not None and instances:
        links = parse_links_from_graph(system_graph, instances)

    return instances, links


def parse_local_replica_graph(graph: Graph,
                              project_uri: Optional[str] = None) -> List[ComponentInstance]:
    """Parse a *standalone* classes_and_attributes graph (e.g. the TTL just
    written by ``process_excel_to_ttl``) into ComponentInstances — no
    triplestore, no ontology.

    Discovery leans on the asserted structure the platform's generators emit:

    * attribute nodes are objects of ``dici_onto:hasAttribute`` /
      ``dici_onto:hasIdentifier`` / any ``dici_onto:has…Attribute`` predicate;
    * component instances are the remaining subjects with a ``dici_onto:``
      rdf:type, excluding ``TimeSeries`` and ``Reference`` nodes;
    * attribute kinds come from each node's asserted kind class
      (``parse_single_attribute``'s fallback path).

    ``project_uri`` additionally recovers free-form Annotation columns the
    Excel converter writes into the project namespace (``:<name> "value"``).
    """
    dici = str(DICI)

    # 1. Attribute + identifier nodes (never instances).
    attr_nodes = set()
    attr_links: Dict[URIRef, List[URIRef]] = {}
    for s, p, o in graph:
        pred = str(p)
        if not pred.startswith(dici):
            continue
        pred_name = pred[len(dici):]
        if pred_name == "hasAttribute" or pred_name == "hasIdentifier" or (
                pred_name.startswith("has") and pred_name.endswith("Attribute")):
            if isinstance(o, URIRef):
                attr_nodes.add(o)
                attr_links.setdefault(s, [])
                if o not in attr_links[s]:
                    attr_links[s].append(o)

    identifier_nodes = set(graph.objects(None, DICI.hasIdentifier))

    # 2. Structural nodes to skip.
    ts_nodes = set(graph.subjects(RDF.type, DICI.TimeSeries))
    ref_nodes = set(graph.subjects(RDF.type, DICI.Reference))

    # 3. Component instances: subjects with a dici_onto: type that aren't
    # attribute / time-series / reference nodes.
    instance_types: Dict[URIRef, str] = {}
    for s, o in graph.subject_objects(RDF.type):
        if not isinstance(s, URIRef) or not isinstance(o, URIRef):
            continue
        if s in attr_nodes or s in ts_nodes or s in ref_nodes:
            continue
        type_str = str(o)
        if not type_str.startswith(dici):
            continue
        type_name = type_str[len(dici):]
        if type_name in ("TimeSeries", "Reference"):
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
        class_objects: Dict[str, str] = {}
        excluded_predicates = {'hasAttribute', 'hasIdentifier', 'label'}
        for p, o in graph.predicate_objects(subject):
            pred_str = str(p)
            if pred_str.startswith(str(RDFS)) and pred_str != str(RDFS.label):
                annotations[pred_str.replace(str(RDFS), "")] = str(o)
            elif project_ns and pred_str.startswith(project_ns) and isinstance(o, Literal):
                # Free-form Annotation columns land in the project namespace.
                annotations[pred_str[len(project_ns):]] = str(o)
            elif pred_str.startswith(dici):
                pred_name = pred_str[len(dici):]
                if pred_name not in excluded_predicates and not pred_name.startswith('has') \
                        and isinstance(o, URIRef):
                    class_objects[pred_name] = str(o)

        instance = ComponentInstance(
            id=uri.split('#')[-1] if '#' in uri else uri.split('/')[-1],
            component_type=type_name,
            uri=uri,
            label=label or (uri.split('#')[-1] if '#' in uri else uri.split('/')[-1]),
            annotations=annotations,
            class_objects=class_objects,
        )

        for attr_uri in attr_links.get(subject, []):
            forced_kind = 'Identifier' if attr_uri in identifier_nodes else None
            attr_data = parse_single_attribute(graph, attr_uri, attr_type=forced_kind)
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
