# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Materialize Sets and GroupedSets into the workspace's collections graph.

Flow (per the collections design): SPARQL SELECT the raw attribute values →
detect the datatype family from the attribute class's base value-type
(``registry``) → compute the statistics in Python → build the collection's
triples with rdflib → surgically replace that collection's triples in
``<http://collections>`` → stamp ``computedAt``/``computedBy``.

Collections are DERIVED artefacts: recomputing one deletes exactly its own
triples first (deterministic IRIs make the subtree addressable), and a
workspace data reload wipes the whole graph (see graphdb_provisioning).
Mixed datatype families and empty member sets fail loudly — never coerced,
never written as empty shells.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

from backend.graphdb.graphs import COLLECTIONS_GRAPH
from . import queries
from .registry import (
    BASE_TYPE_FAMILY, BOOLEAN, CATEGORICAL, NUMERIC, SIMPLE_VALUE_BASE,
    TEMPORAL, UNSUPPORTED_BASE_TYPES, CollectionError, compute_stats,
    sniff_family,
)

dici_onto = Namespace("https://digicities.info/ontology#")
QUDT = Namespace("http://qudt.org/schema/qudt/")

COMPUTED_BY = "digicities-collections/0.1"
_PROJ_PREFIX = "https://digicities.info/proj"


def _local(iri: str) -> str:
    return str(iri).rstrip("#/").split("#")[-1].split("/")[-1]


def _slug(value: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", str(value)).strip("_")
    return s or "value"


def _collections_base(workspace_id: str) -> str:
    return f"{_PROJ_PREFIX}/{workspace_id}/collections"


def detect_family(client, attribute_class_iri: str) -> Tuple[str, bool]:
    """Datatype family of an attribute class, from its base value-type in the
    schema graph. Returns ``(family, is_simple_value)`` — a SimpleValue result
    still needs refinement by value sniffing."""
    bases = set(queries.base_types_of(client, attribute_class_iri))
    if not bases:
        raise CollectionError(
            f"{attribute_class_iri} is not an Attribute subclass in this "
            f"workspace's schema graph")
    unsupported = bases & UNSUPPORTED_BASE_TYPES
    if unsupported:
        raise CollectionError(
            f"{_local(attribute_class_iri)} is a {sorted(unsupported)[0]} — "
            f"its values are not scalar and cannot form a Set")
    for base, family in BASE_TYPE_FAMILY.items():
        if base in bases:
            return family, False
    if SIMPLE_VALUE_BASE in bases:
        return CATEGORICAL, True     # refined by sniff_family on the raw values
    raise CollectionError(
        f"{_local(attribute_class_iri)} has no recognised base value-type "
        f"(found: {sorted(bases)})")


def _row_value(row, family: str, num_col: str, simple_col: str,
               cat_col: str, cat_label_col: str) -> Optional[str]:
    """The raw value of one attribute node under the family's value predicate.
    Categorical URI values collapse to their label (fallback: local name)."""
    def has(col):
        v = row.get(col)
        return v is not None and not pd.isna(v) and str(v) != ""

    if has(cat_col):
        return str(row[cat_label_col]) if has(cat_label_col) else _local(row[cat_col])
    if family == NUMERIC and has(num_col):
        return str(row[num_col])
    if has(simple_col):
        return str(row[simple_col])
    if has(num_col):
        return str(row[num_col])
    return None


def _values_and_members(df: pd.DataFrame, family: str,
                        is_simple: bool) -> Tuple[str, List[str], List[str]]:
    """Extract (refined_family, values, member_iris) from a member query
    result, dropping value-less nodes."""
    values, members = [], []
    for _, row in df.iterrows():
        v = _row_value(row, family, "numValue", "simpleValue", "catValue", "catLabel")
        if v is not None:
            values.append(v)
            members.append(str(row["attr"]))
    if not values:
        raise CollectionError("no attribute values found — nothing to aggregate")
    if is_simple:
        family = sniff_family(values)
    return family, values, members


def _stats_node(g: Graph, set_iri: URIRef, stats: Dict, bins: List[Dict]) -> None:
    """Attach a DescriptiveStatistics node (and Distribution bins) to a Set."""
    stats_iri = URIRef(f"{set_iri}/stats")
    g.add((set_iri, dici_onto.hasDescriptiveStatistics, stats_iri))
    g.add((stats_iri, RDF.type, dici_onto.DescriptiveStatistics))
    for name, value in stats.items():
        pred = dici_onto[name]
        for v in (value if isinstance(value, list) else [value]):
            if isinstance(v, int):
                g.add((stats_iri, pred, Literal(v, datatype=XSD.integer)))
            elif isinstance(v, float):
                g.add((stats_iri, pred, Literal(v, datatype=XSD.double)))
            else:
                g.add((stats_iri, pred, Literal(str(v))))
    if bins:
        dist_iri = URIRef(f"{set_iri}/distribution")
        g.add((set_iri, dici_onto.hasDistribution, dist_iri))
        g.add((dist_iri, RDF.type, dici_onto.Distribution))
        for i, b in enumerate(bins):
            bin_iri = URIRef(f"{set_iri}/bin/{i}")
            g.add((dist_iri, dici_onto.hasBin, bin_iri))
            g.add((bin_iri, RDF.type, dici_onto.DistributionBin))
            g.add((bin_iri, dici_onto.binLabel, Literal(b["label"])))
            g.add((bin_iri, dici_onto.binFrequency,
                   Literal(int(b["frequency"]), datatype=XSD.integer)))
            if b.get("lower") is not None:
                g.add((bin_iri, dici_onto.binLowerBound,
                       Literal(float(b["lower"]), datatype=XSD.double)))
            if b.get("upper") is not None:
                g.add((bin_iri, dici_onto.binUpperBound,
                       Literal(float(b["upper"]), datatype=XSD.double)))


def _provenance(g: Graph, coll_iri: URIRef, attribute_class_iri: str,
                dataset_iri: Optional[str]) -> None:
    g.add((coll_iri, dici_onto.ofAttributeType, URIRef(attribute_class_iri)))
    g.add((coll_iri, dici_onto.computedAt,
           Literal(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   datatype=XSD.dateTime)))
    g.add((coll_iri, dici_onto.computedBy, Literal(COMPUTED_BY)))
    if dataset_iri:
        g.add((coll_iri, dici_onto.derivedFromDataSet, URIRef(dataset_iri)))
        g.add((URIRef(dataset_iri), dici_onto.hasSet, coll_iri))


def _replace_collection(client, root_iri: str, g: Graph) -> None:
    """Surgically replace one collection's triples in the collections graph:
    delete everything minted under the root IRI (subjects AND objects — the
    membership/hasSet triples point at it), then insert the new content.

    Projected aggregate nodes live under their CONTAINER's IRI, not the
    collection root, so they are found via their ``aggregateOf`` link to a
    group Set under the root — first the edges pointing at them, then their
    own triples. (Shared aggregate CLASS declarations are left in place: they
    are identical across collections and re-asserted on insert.)"""
    graph = f"<{COLLECTIONS_GRAPH}>"
    root = str(root_iri)
    under_root = (f'(STR(?set) = "{root}" || STRSTARTS(STR(?set), "{root}/"))')
    agg_updates = (
        # edges INTO each projected node (hasAttribute / has<C><A>Attribute)
        f"DELETE {{ GRAPH {graph} {{ ?s ?p ?n }} }} WHERE {{ GRAPH {graph} {{ "
        f"?n <{dici_onto.aggregateOf}> ?set . FILTER({under_root}) ?s ?p ?n }} }}",
        # the projected nodes' own triples (removes aggregateOf itself last)
        f"DELETE {{ GRAPH {graph} {{ ?n ?p ?o }} }} WHERE {{ GRAPH {graph} {{ "
        f"?n <{dici_onto.aggregateOf}> ?set . FILTER({under_root}) ?n ?p ?o }} }}",
    )
    for upd in agg_updates:
        client.sparql_update(upd)
    for pattern, flt in (
        ("?s ?p ?o", f'FILTER(STR(?s) = "{root}" || STRSTARTS(STR(?s), "{root}/"))'),
        ("?s ?p ?o", f'FILTER(isIRI(?o) && (STR(?o) = "{root}" || STRSTARTS(STR(?o), "{root}/")))'),
    ):
        client.sparql_update(
            f"DELETE {{ GRAPH {graph} {{ {pattern} }} }} "
            f"WHERE {{ GRAPH {graph} {{ {pattern} . {flt} }} }}")
    nt = g.serialize(format="nt")
    if nt.strip():
        client.sparql_update(f"INSERT DATA {{ GRAPH {graph} {{\n{nt}\n}} }}")


def delete_collection(client, collection_iri: str) -> None:
    """Remove a materialized collection (and its stats/bins/groups/membership
    triples) from the collections graph."""
    _replace_collection(client, collection_iri, Graph())


def materialize_set(client, workspace_id: str, attribute_class_iri: str,
                    dataset_iri: Optional[str] = None) -> str:
    """Materialize the Set of every value of one attribute type in the
    workspace replica (optionally restricted to components citing one data
    source). Returns the Set IRI. Raises CollectionError when there is nothing
    valid to aggregate."""
    family, is_simple = detect_family(client, attribute_class_iri)
    df = queries.member_values(client, attribute_class_iri, dataset_iri)
    family, values, members = _values_and_members(df, family, is_simple)
    stats, bins = compute_stats(family, values)

    name = f"{_local(attribute_class_iri)}Set"
    if dataset_iri:
        name += f"_{_slug(_local(dataset_iri))}"
    set_iri = URIRef(f"{_collections_base(workspace_id)}/{name}")

    g = Graph()
    g.add((set_iri, RDF.type, dici_onto.Set))
    g.add((set_iri, RDFS.label,
           Literal(f"{_local(attribute_class_iri)} set ({family})")))
    _provenance(g, set_iri, attribute_class_iri, dataset_iri)
    for m in members:
        g.add((URIRef(m), dici_onto.aggregatedIn, set_iri))
    _stats_node(g, set_iri, stats, bins)

    _replace_collection(client, str(set_iri), g)
    return str(set_iri)


def materialize_grouped_set(client, workspace_id: str,
                            target_attribute_class_iri: str,
                            grouping_class_iri: str,
                            dataset_iri: Optional[str] = None,
                            project_statistics=("mean",)) -> str:
    """Materialize a GroupedSet: the target attribute's values partitioned by
    the grouping class — one member Set (with statistics) per distinct group
    key. Returns the GroupedSet IRI.

    The ontology decides the grouping mode. A grouping class under
    ``dici_onto:Component`` groups by COMPONENT: one group per instance of
    that class the members' owners are linked to (linksComponent-family edges,
    either direction) — e.g. per-park turbine statistics. Any other grouping
    class is an attribute type on the same components, and must be categorical
    (or a boolean/string simple value): grouping by raw continuous values is
    rejected, as every group would hold one member."""
    if queries.is_component_class(client, grouping_class_iri):
        return materialize_component_grouped_set(
            client, workspace_id, target_attribute_class_iri,
            grouping_class_iri, dataset_iri,
            project_statistics=project_statistics)
    grouping_attribute_class_iri = grouping_class_iri
    t_family, t_simple = detect_family(client, target_attribute_class_iri)
    g_family, g_simple = detect_family(client, grouping_attribute_class_iri)

    df = queries.grouped_member_values(
        client, target_attribute_class_iri, grouping_attribute_class_iri,
        dataset_iri)

    # Group keys first — their family gates the whole operation.
    keyed: List[Tuple[str, str, str]] = []   # (group_key, value, member_iri)
    for _, row in df.iterrows():
        key = _row_value(row, g_family, "gNumValue", "gSimpleValue",
                         "gCatValue", "gCatLabel")
        val = _row_value(row, t_family, "numValue", "simpleValue",
                         "catValue", "catLabel")
        if key is not None and val is not None:
            keyed.append((key, val, str(row["attr"])))
    if not keyed:
        raise CollectionError(
            "no component carries both attribute types with values — "
            "nothing to group")

    g_keys = [k for k, _, _ in keyed]
    effective_g_family = sniff_family(g_keys) if g_simple else g_family
    if effective_g_family not in (CATEGORICAL, BOOLEAN):
        raise CollectionError(
            f"grouping by {_local(grouping_attribute_class_iri)} "
            f"({effective_g_family}) is rejected — group keys must be "
            f"categorical or boolean, not raw continuous values")

    target_values = [v for _, v, _ in keyed]
    effective_t_family = sniff_family(target_values) if t_simple else t_family

    base = _collections_base(workspace_id)
    name = (f"{_local(target_attribute_class_iri)}By"
            f"{_local(grouping_attribute_class_iri)}")
    if dataset_iri:
        name += f"_{_slug(_local(dataset_iri))}"
    gset_iri = URIRef(f"{base}/{name}")

    g = Graph()
    g.add((gset_iri, RDF.type, dici_onto.GroupedSet))
    g.add((gset_iri, RDFS.label,
           Literal(f"{_local(target_attribute_class_iri)} by "
                   f"{_local(grouping_attribute_class_iri)}")))
    _provenance(g, gset_iri, target_attribute_class_iri, dataset_iri)
    g.add((gset_iri, dici_onto.groupedBy, URIRef(grouping_attribute_class_iri)))

    groups: Dict[str, List[Tuple[str, str]]] = {}
    for key, val, member in keyed:
        groups.setdefault(key, []).append((val, member))

    for key in sorted(groups):
        vals = [v for v, _ in groups[key]]
        stats, bins = compute_stats(effective_t_family, vals)   # fails loudly
        member_set = URIRef(f"{gset_iri}/group/{_slug(key)}")
        g.add((gset_iri, dici_onto.hasGroup, member_set))
        g.add((member_set, RDF.type, dici_onto.Set))
        g.add((member_set, RDFS.label,
               Literal(f"{_local(target_attribute_class_iri)} where "
                       f"{_local(grouping_attribute_class_iri)} = {key}")))
        g.add((member_set, dici_onto.ofAttributeType,
               URIRef(target_attribute_class_iri)))
        g.add((member_set, dici_onto.groupKey, Literal(key)))
        for _, member in groups[key]:
            g.add((URIRef(member), dici_onto.aggregatedIn, member_set))
        _stats_node(g, member_set, stats, bins)

    _replace_collection(client, str(gset_iri), g)
    return str(gset_iri)


def materialize_component_grouped_set(client, workspace_id: str,
                                      target_attribute_class_iri: str,
                                      grouping_component_class_iri: str,
                                      dataset_iri: Optional[str] = None,
                                      project_statistics=("mean",)) -> str:
    """Materialize a component-grouped GroupedSet: the target attribute's
    values partitioned by the instances of a component class the owners are
    linked to (e.g. HubHeight per WindPark). One group Set per container
    instance, carrying ``groupComponent`` (the instance) and ``groupKey``
    (its label). Returns the GroupedSet IRI.

    For a NUMERIC target, each statistic in ``project_statistics`` is also
    PROJECTED onto the container as a derived attribute node in the exact
    shape authored attributes take — ``<container>/<Attr><Stat>`` typed
    ``<Attr><Stat>``/``AggregateAttribute``/``PhysicalAttribute``, attached
    via ``hasAttribute`` + ``has<Class><Attr><Stat>Attribute``, valued with
    ``qudt:value``/``qudt:unit`` — so a service template can request e.g.
    ``District.FloorAreaMean`` exactly like any Component.attribute. Pass an
    empty tuple to skip projection."""
    if not queries.is_component_class(client, grouping_component_class_iri):
        raise CollectionError(
            f"{_local(grouping_component_class_iri)} is not a Component "
            f"subclass in this workspace's schema graph")
    t_family, t_simple = detect_family(client, target_attribute_class_iri)

    df = queries.component_grouped_member_values(
        client, target_attribute_class_iri, grouping_component_class_iri,
        dataset_iri)

    # (container_iri, container_label, value, member_iri) — keyed by the
    # container INSTANCE, never its label (labels may collide).
    keyed: List[Tuple[str, str, str, str]] = []
    units: Dict[str, str] = {}          # container → first member unit IRI
    unit_labels: Dict[str, str] = {}
    for _, row in df.iterrows():
        val = _row_value(row, t_family, "numValue", "simpleValue",
                         "catValue", "catLabel")
        container = row.get("container")
        if val is None or container is None or pd.isna(container):
            continue
        label = row.get("containerLabel")
        label = (str(label) if label is not None and not pd.isna(label)
                 and str(label) else _local(container))
        keyed.append((str(container), label, val, str(row["attr"])))
        for col, store in (("unit", units), ("unitLabel", unit_labels)):
            v = row.get(col)
            if str(container) not in store and v is not None and not pd.isna(v) and str(v):
                store[str(container)] = str(v)
    if not keyed:
        raise CollectionError(
            f"no {_local(target_attribute_class_iri)} value sits on a "
            f"component linked to a {_local(grouping_component_class_iri)} — "
            f"nothing to group")

    effective_t_family = (sniff_family([v for _, _, v, _ in keyed])
                          if t_simple else t_family)

    base = _collections_base(workspace_id)
    name = (f"{_local(target_attribute_class_iri)}By"
            f"{_local(grouping_component_class_iri)}")
    if dataset_iri:
        name += f"_{_slug(_local(dataset_iri))}"
    gset_iri = URIRef(f"{base}/{name}")

    g = Graph()
    g.add((gset_iri, RDF.type, dici_onto.GroupedSet))
    g.add((gset_iri, RDFS.label,
           Literal(f"{_local(target_attribute_class_iri)} per "
                   f"{_local(grouping_component_class_iri)}")))
    _provenance(g, gset_iri, target_attribute_class_iri, dataset_iri)
    g.add((gset_iri, dici_onto.groupedBy,
           URIRef(grouping_component_class_iri)))

    groups: Dict[str, List[Tuple[str, str]]] = {}
    labels: Dict[str, str] = {}
    for container, label, val, member in keyed:
        groups.setdefault(container, []).append((val, member))
        labels[container] = label

    attr_local = _local(target_attribute_class_iri)
    comp_local = _local(grouping_component_class_iri)
    from .registry import NUMERIC as _NUM
    project = tuple(project_statistics or ()) if effective_t_family == _NUM else ()
    if project_statistics and effective_t_family != _NUM:
        print(f"[collections] projection skipped: {attr_local} is "
              f"{effective_t_family}, only numeric statistics are projected")

    for container in sorted(groups):
        vals = [v for v, _ in groups[container]]
        stats, bins = compute_stats(effective_t_family, vals)   # fails loudly
        member_set = URIRef(f"{gset_iri}/group/{_slug(_local(container))}")
        g.add((gset_iri, dici_onto.hasGroup, member_set))
        g.add((member_set, RDF.type, dici_onto.Set))
        g.add((member_set, RDFS.label,
               Literal(f"{attr_local} of components "
                       f"linked to {labels[container]}")))
        g.add((member_set, dici_onto.ofAttributeType,
               URIRef(target_attribute_class_iri)))
        g.add((member_set, dici_onto.groupKey, Literal(labels[container])))
        g.add((member_set, dici_onto.groupComponent, URIRef(container)))
        for _, member in groups[container]:
            g.add((URIRef(member), dici_onto.aggregatedIn, member_set))
        _stats_node(g, member_set, stats, bins)

        # Project the requested statistics onto the container as derived
        # attribute nodes — the exact shape the replica converter authors, so
        # Component.attribute requests (e.g. District.FloorAreaMean) resolve
        # through the ordinary service-template pipeline.
        for stat in project:
            if stat not in stats:
                continue                      # e.g. stdev on a 1-member group
            agg_name = f"{attr_local}{stat[0].upper()}{stat[1:]}"
            node = URIRef(f"{container}/{agg_name}")
            cont_ref = URIRef(container)
            g.add((cont_ref, dici_onto.hasAttribute, node))
            g.add((cont_ref, dici_onto[f"has{comp_local}{agg_name}Attribute"], node))
            g.add((node, RDF.type, dici_onto[agg_name]))
            g.add((node, RDF.type, dici_onto.AggregateAttribute))
            g.add((node, RDF.type, dici_onto.PhysicalAttribute))
            g.add((node, RDFS.label,
                   Literal(f"{stat} of {stats['count']} {attr_local} values")))
            g.add((node, QUDT.value,
                   Literal(f"{float(stats[stat]):g}", datatype=XSD.decimal)))
            if container in units:
                g.add((node, QUDT.unit, URIRef(units[container])))
            if container in unit_labels:
                g.add((node, dici_onto.hasUnitLabel, Literal(unit_labels[container])))
            g.add((node, dici_onto.aggregateOf, member_set))
            g.add((node, dici_onto.statisticUsed, Literal(stat)))

    # Declare each projected aggregate class once, in the collections graph
    # (derived schema for derived nodes — wiped with the rest on reload).
    for stat in project:
        agg_name = f"{attr_local}{stat[0].upper()}{stat[1:]}"
        g.add((dici_onto[agg_name], RDF.type,
               URIRef("http://www.w3.org/2002/07/owl#Class")))
        g.add((dici_onto[agg_name], RDFS.subClassOf, dici_onto.AggregateAttribute))
        g.add((dici_onto[agg_name], RDFS.label,
               Literal(f"{attr_local} {stat} (aggregate)")))

    _replace_collection(client, str(gset_iri), g)
    return str(gset_iri)
