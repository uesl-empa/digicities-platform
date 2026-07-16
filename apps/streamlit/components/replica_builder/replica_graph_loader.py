# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_graph_loader.py
"""
Graph Loader for Replica Builder
Loads existing graphs from GraphDB
"""
import streamlit as st
from typing import Optional, Dict, List, Any
from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS
from rdflib.namespace import DCTERMS

from backend.graphdb.graphs import (
    CLASSES_AND_ATTRIBUTES_GRAPH,
    SYSTEM_DESCRIPTION_GRAPH,
)
from backend.graphdb.queries import graph_io
from backend.graphdb.queries import components as components_q

DICI = Namespace("https://digicities.info/ontology#")


def load_existing_graphs(client, populate_instances=False) -> bool:
    """Load existing graphs from GraphDB and optionally populate instances"""
    if not client:
        return False

    try:
        # Load classes_and_attributes graph
        classes_graph = load_classes_and_attributes_graph(client)
        if classes_graph:
            st.session_state.replica_existing_classes_graph = classes_graph

            # Optionally populate instances from the loaded graph
            if populate_instances:
                # Discover instances, their leaf component type, and their
                # attribute nodes with SPARQL over the ontology hierarchy
                # (rdfs:subClassOf* / rdfs:subPropertyOf*). The constructed graph
                # below is used only to read literal values off those nodes.
                discovered = components_q.get_all_component_instances(client)
                attr_links = components_q.get_all_instance_attribute_links(client)
                attr_kinds = components_q.get_attribute_kinds(client)
                instances = parse_instances_from_graph(classes_graph, discovered)
                attributes = parse_attributes_from_graph(classes_graph, attr_links, attr_kinds)

                # Convert to replica builder format (must be done before links!)
                st.session_state.replica_instances = convert_to_replica_instances(instances, attributes)
                st.success(f"✅ Loaded {len(st.session_state.replica_instances)} instances from classes_and_attributes graph")

        # Load system_description graph
        system_graph = load_system_description_graph(client)
        if system_graph:
            st.session_state.replica_existing_system_graph = system_graph

            # Optionally populate links from the loaded graph (must be AFTER instances!)
            if populate_instances and st.session_state.replica_instances:
                links = parse_links_from_graph(system_graph)
                st.session_state.replica_links = links
                if links:
                    st.success(f"✅ Loaded {len(st.session_state.replica_links)} links from system_description graph")
                else:
                    st.info("ℹ️ No links found in system_description graph")

        return True

    except Exception as e:
        st.error(f"Failed to load existing graphs: {e}")
        import traceback
        st.error(traceback.format_exc())
        return False


def load_classes_and_attributes_graph(client) -> Optional[Graph]:
    """Load the classes_and_attributes named graph (via backend.graphdb.queries.graph_io)."""
    graph = graph_io.construct_named_graph(client, CLASSES_AND_ATTRIBUTES_GRAPH)
    if graph is None:
        st.warning("Could not load classes_and_attributes graph")
    return graph


def load_system_description_graph(client) -> Optional[Graph]:
    """Load the system_description named graph (via backend.graphdb.queries.graph_io)."""
    graph = graph_io.construct_named_graph(client, SYSTEM_DESCRIPTION_GRAPH)
    if graph is None:
        st.warning("Could not load system_description graph")
    return graph


def _local_name(uri: str) -> str:
    """Local name of a URI (after '#', else after the last '/')."""
    return uri.split("#")[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


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
        label = row["label"] if isinstance(row.get("label"), str) and row["label"] else _local_name(uri)

        instance_data = {
            'uri': uri,
            'type': _local_name(str(row["type"])),
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
        kind_local = _local_name(str(row["kind"]))
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
    QUDT_NS = Namespace("http://qudt.org/schema/qudt/")
    UNIT_NS = Namespace("http://qudt.org/vocab/unit/")

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


def parse_single_attribute(graph: Graph, attr_uri, QUDT_NS, UNIT_NS,
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
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    elif attr_type == 'Geospatial':
        # Get geospatial value
        for value in graph.objects(attr_uri, DICI.hasAttributeValue):
            attr_data['value'] = str(value)
        for source in graph.objects(attr_uri, DCTERMS.source):
            attr_data['datasource'] = str(source)

    return attr_data


def convert_to_replica_instances(instances: List[Dict[str, Any]],
                                  attributes: Dict[str, List[Dict[str, Any]]]):
    """Convert parsed graph data to replica builder instance format"""
    from components.replica_builder.replica_instance_manager import ComponentInstance

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


def parse_links_from_graph(graph: Graph) -> List[Dict[str, Any]]:
    """Parse links from system_description graph"""
    links = []

    # First, create maps by both ID and URI for instance lookups
    instances_by_id = {}
    instances_by_uri = {}
    for inst in st.session_state.replica_instances:
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


def show_existing_graphs_status(client):
    """Display status of existing graphs"""

    with st.expander("Existing Graphs in Triplestore", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📥 Load Graphs", type="secondary", use_container_width=True):
                with st.spinner("Loading graphs from Triplestore..."):
                    if load_existing_graphs(client, populate_instances=False):
                        st.success("✅ Graphs loaded successfully")
                        st.rerun()

        with col2:
            # Show populate button only if graphs are loaded
            if st.session_state.replica_existing_classes_graph:
                if st.button("📋 Populate Instances", type="primary", use_container_width=True):
                    with st.spinner("Populating instances from graphs..."):
                        if load_existing_graphs(client, populate_instances=True):
                            st.rerun()

        with col3:
            if st.session_state.replica_existing_classes_graph or st.session_state.replica_existing_system_graph:
                if st.button("🗑️ Clear", use_container_width=True):
                    st.session_state.replica_existing_classes_graph = None
                    st.session_state.replica_existing_system_graph = None
                    st.session_state.replica_instances = []
                    st.session_state.replica_links = []
                    st.rerun()

        st.markdown("---")

        # Show status
        if st.session_state.replica_existing_classes_graph:
            classes_graph = st.session_state.replica_existing_classes_graph
            triple_count = len(classes_graph)
            discovered = components_q.get_all_component_instances(client)
            instance_count = 0 if discovered is None else len(discovered)

            st.success(f"**classes_and_attributes**: {triple_count} triples, {instance_count} instances found")

            # Show if instances have been populated
            if st.session_state.replica_instances:
                st.info(f"📋 {len(st.session_state.replica_instances)} instances loaded into replica builder")
        else:
            st.info("**classes_and_attributes**: Not loaded")

        if st.session_state.replica_existing_system_graph:
            system_graph = st.session_state.replica_existing_system_graph
            triple_count = len(system_graph)
            links = parse_links_from_graph(system_graph)

            st.success(f"**system_description**: {triple_count} triples, {len(links)} links found")

            # Show if links have been populated
            if st.session_state.replica_links:
                st.info(f"🔗 {len(st.session_state.replica_links)} links loaded into replica builder")
        else:
            st.info("**system_description**: Not loaded")

        # Help text
        st.markdown("---")
        st.caption("**ℹ️ How to use:**")
        st.caption("""
        **1. Load Graphs** → Fetch existing data from Triplestore
        **2. Populate Instances** → Import data into replica builder
        **3. Clear** → Remove loaded graphs and instances
        """)