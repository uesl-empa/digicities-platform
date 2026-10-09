# SPDX-License-Identifier: Apache-2.0

"""The scenario builder's dicts read through the ontology, never by spelling.

The builder carries graph terms around as plain strings: a component's
``type`` is a class local name, ``nested_properties`` keys are property local
names (``hasLiveTimeSeriesReference``), and an attribute's ``attribute_type``
names its value shape. Every question about what such a string MEANS goes
through here: the string becomes the ``dici_onto:`` IRI it names and the core
hierarchy (``backend.ontology_kinds``) answers. A substring of the name never
decides anything.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Mapping, Optional, Tuple

from rdflib import RDF, Graph, URIRef

from backend.ontology_kinds import (
    DICI,
    AttributeKind,
    attribute_kind,
    is_component_link_class,
    is_scenario_class,
    is_subclass_of,
    is_subproperty_of,
    is_time_series_predicate,
    is_time_series_reference_predicate,
    with_core,
)

# The attribute links and the reference literals the builder reads off a
# dynamic attribute, in the order the emitter has always preferred them.
TIME_SERIES_LINKS = (DICI.hasHistoricTimeSeries, DICI.hasLiveTimeSeries,
                     DICI.hasFutureTimeSeries)
TIME_SERIES_REFERENCES = (DICI.hasHistoricTimeSeriesReference,
                          DICI.hasLiveTimeSeriesReference,
                          DICI.hasFutureTimeSeriesReference)


@lru_cache(maxsize=1)
def core() -> Graph:
    """The core ontology as a read-only graph (built once per process)."""
    return with_core(Graph())


def local_key(term: URIRef) -> str:
    """The dict key the builder files a ``dici_onto:`` term under."""
    return str(term)[len(str(DICI)):]


def term(name: Any) -> Optional[URIRef]:
    """The ``dici_onto:`` IRI a builder string names, or None when the string
    cannot be a local name at all."""
    if isinstance(name, str) and name.isidentifier():
        return DICI[name]
    return None


def names_scenario_class(name: Any) -> bool:
    t = term(name)
    return t is not None and is_scenario_class(core(), t)


def names_component_link_class(name: Any) -> bool:
    t = term(name)
    return t is not None and is_component_link_class(core(), t)


def is_time_series_key(key: Any) -> bool:
    """``key`` names a link to a TimeSeries node (``hasLiveTimeSeries``)."""
    t = term(key)
    return t is not None and is_time_series_predicate(core(), t)


def is_time_series_reference_key(key: Any) -> bool:
    """``key`` names a time series reference literal (``hasLiveTimeSeriesReference``)."""
    t = term(key)
    return t is not None and is_time_series_reference_predicate(core(), t)


def has_time_series_data(keys: Iterable[Any]) -> bool:
    """Any of ``keys`` carries a time series link or reference."""
    return any(is_time_series_key(k) or is_time_series_reference_key(k) for k in keys)


def first_present(data: Mapping[str, Any],
                  props: Iterable[URIRef]) -> Optional[Tuple[URIRef, Any]]:
    """The first of ``props`` the dict holds a value for, as ``(prop, value)``."""
    for prop in props:
        key = local_key(prop)
        if key in data:
            return prop, data[key]
    return None


def as_attribute_kind(tag: Any) -> Optional[AttributeKind]:
    """The kind an ``attribute_type`` value names.

    Accepts an ``AttributeKind``, its editor tag (``"Dynamic"``), or the local
    name of a class under one of the kind classes (``"DynamicAttribute"``,
    ``"ElectricityDemandProfile"``), which is what older drafts and REST
    clients send. Anything else (``"system"``, ``"unknown"``) is no kind.
    """
    if isinstance(tag, AttributeKind):
        return tag
    if not isinstance(tag, str):
        return None
    try:
        return AttributeKind(tag)
    except ValueError:
        t = term(tag)
        return attribute_kind(core(), [t]) if t is not None else None


def kind_of(attr_data: Any) -> Optional[AttributeKind]:
    """The kind of a builder attribute dict (None for system entries and
    attributes nobody typed)."""
    if not isinstance(attr_data, Mapping):
        return None
    return as_attribute_kind(attr_data.get('attribute_type'))


def names_subclass_of(name: Any, sup: Any) -> bool:
    """``name`` names ``sup`` or a class under it (``rdfs:subClassOf*``)."""
    t, s = term(name), term(sup)
    return t is not None and s is not None and (t == s or is_subclass_of(core(), t, s))


def property_matches(key: Any, wanted: Any) -> bool:
    """``key`` names the property ``wanted`` or a subproperty of it, so a
    requirement for ``hasTimeSeriesReference`` is met by a stored
    ``hasLiveTimeSeriesReference``."""
    k, w = term(key), term(wanted)
    return k is not None and w is not None and (k == w or is_subproperty_of(core(), k, w))


# Returned by the lookups below when nothing matches (None can be a value).
MISSING = object()


def find_property(data: Mapping[str, Any], wanted: Any) -> Any:
    """The value ``data`` holds for the property ``wanted`` (or a subproperty),
    else ``MISSING``. An exact key wins over a subproperty."""
    if wanted in data:
        return data[wanted]
    for key, value in data.items():
        if property_matches(key, wanted):
            return value
    return MISSING

# The loaders file a dynamic attribute's reference under the builder's own
# ``time_series_reference`` key with ``time_series_type`` naming the series;
# this is the reference property each series type stands for.
_SERIES_REFERENCE = {
    'historic': DICI.hasHistoricTimeSeriesReference,
    'live': DICI.hasLiveTimeSeriesReference,
    'future': DICI.hasFutureTimeSeriesReference,
    'generic': DICI.hasTimeSeriesReference,
    '': DICI.hasTimeSeriesReference,
}


def stored_series_reference(attr_data: Mapping[str, Any], wanted: Any) -> Any:
    """The loader-stored time series reference when its series' reference
    property meets ``wanted``, else ``MISSING``."""
    ref = attr_data.get('time_series_reference')
    prop = _SERIES_REFERENCE.get(attr_data.get('time_series_type') or '')
    if ref is not None and prop is not None and property_matches(local_key(prop), wanted):
        return ref
    return MISSING


def precision_term(name: Any) -> Optional[URIRef]:
    """The ``dici_onto:TemporalPrecision`` individual ``name`` names, or None
    when it names none (the core's individuals are the allowed values)."""
    t = term(name)
    if t is not None and (t, RDF.type, DICI.TemporalPrecision) in core():
        return t
    return None


def is_unknown_precision(name: Any) -> bool:
    """``name`` names the core's ``Unknown`` precision (no precision given)."""
    return precision_term(name) == DICI.Unknown
