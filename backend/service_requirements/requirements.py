# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The requirements TTL a service publishes into its workspace.

A service's requirements are recorded as one ``dici_onto:Service`` node plus
numbered requirement nodes: ``ComponentAttributeRequirement`` (this service
needs attribute A of component type C) and ``ComponentComponentRequirement``
(this service needs C1 linked to C2). Built with rdflib rather than string
templates, so user-supplied labels (quotes, newlines, unicode) are escaped by
the serializer instead of by hand — a hostile label can never break or
rewrite the document.

Replaces the hand-written f-string TTL that lived in ``apps/api/service.py``.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from backend.service_requirements.contract import OutputAttribute, OutputBlock
from backend.service_requirements.template import pascal_case

DICI = Namespace("https://digicities.info/ontology#")


def service_file_id(service_name: str) -> str:
    """The filesystem-safe service id used for saved files and the service URI.

    PascalCase, capped at 40 characters, never empty ("Service" fallback).
    """
    return pascal_case(service_name)[:40] or "Service"


def requirements_ttl(
    service_name: str,
    label: str,
    requirements: Iterable[Tuple[str, Sequence[str]]],
    links: Iterable[Tuple[str, str]],
    base: str,
    outputs: Iterable = (),
) -> str:
    """Serialize a service's requirements as Turtle.

    ``requirements`` yields (component, attribute names) pairs — one
    ``ComponentAttributeRequirement`` per attribute; ``links`` yields
    (domain, range) component pairs — one ``ComponentComponentRequirement``
    each. ``base`` is the URI prefix requirement nodes live under (ends with
    ``/``, e.g. ``https://digicities.info/proj/<ws>/services/``). Requirement
    nodes are numbered ``req_1..req_n`` across both kinds, attribute
    requirements first.

    ``outputs`` yields what the service PRODUCES, one
    ``ComponentAttributeOutput`` per attribute: either (component, attribute
    names, stream address) triples, or the ``OutputBlock`` s of a contract's
    ``outputs`` block, which add the result field, its unit and the field naming
    the instance. ``providesOutputEntity`` is the input component a result
    belongs to. Before this the TTL marked everything ``hasInputEntity``: a
    reader could not tell the model's products from its inputs. The vocabulary
    is core since v0.8.0, and stays declared here too so that a graph on an
    older vendored core can still read the file.

    What the service READS from a live stream needs nothing extra here: the
    stream's component is an input like any other (a requirement on its
    attribute), and the stream's address is that attribute's
    ``hasLiveTimeSeriesReference`` in the replica, one source of truth.
    """
    g = Graph()
    g.bind("dici_onto", DICI)
    g.bind("rdfs", RDFS)

    service = URIRef(f"{base}{service_file_id(service_name)}")
    g.add((service, RDF.type, DICI.Service))
    g.add((service, RDFS.label, Literal(label or service_name, lang="en")))

    n = 0
    for component, attributes in requirements:
        comp = pascal_case(component)
        for attr in attributes:
            n += 1
            req = URIRef(f"{base}req_{n}")
            g.add((req, RDF.type, DICI.ComponentAttributeRequirement))
            g.add((req, DICI.isRequiredBy, service))
            g.add((req, DICI.hasInputEntity, DICI[comp]))
            g.add((req, DICI.hasInputAttribute, DICI[attr]))
            g.add((req, RDFS.label, Literal(f"{comp}.{attr} required", lang="en")))

    for domain, range_ in links:
        n += 1
        dom, rng = pascal_case(domain), pascal_case(range_)
        req = URIRef(f"{base}req_{n}")
        g.add((req, RDF.type, DICI.ComponentComponentRequirement))
        g.add((req, DICI.isRequiredBy, service))
        g.add((req, DICI.hasInputEntity, DICI[dom]))
        g.add((req, DICI.hasInputEntity, DICI[rng]))
        g.add((req, RDFS.label, Literal(f"{dom} linked to {rng}", lang="en")))

    outputs = list(outputs or ())
    if outputs:
        g.bind("owl", OWL)
        g.add((DICI.ComponentAttributeOutput, RDF.type, OWL.Class))
        g.add((DICI.ComponentAttributeOutput, RDFS.comment, Literal(
            "This service PRODUCES this attribute of this component type "
            "(workspace-extension vocabulary, pending core promotion)", lang="en")))
        for prop, kind in ((DICI.isProvidedBy, OWL.ObjectProperty),
                           (DICI.providesOutputEntity, OWL.ObjectProperty),
                           (DICI.providesOutputAttribute, OWL.ObjectProperty),
                           (DICI.atStreamAddress, OWL.DatatypeProperty),
                           (DICI.hasResultField, OWL.DatatypeProperty),
                           (DICI.identifiedByField, OWL.DatatypeProperty)):
            g.add((prop, RDF.type, kind))
    m = 0
    for item in outputs:
        if isinstance(item, OutputBlock):
            component, address, identified_by = item.component, item.stream, item.identified_by
            produced = list(item.attributes)
        else:
            component, attributes, address = item
            identified_by = None
            produced = [OutputAttribute(a) for a in attributes]
        comp = pascal_case(component)
        for output in produced or [OutputAttribute("")]:
            attr = output.attribute
            m += 1
            out = URIRef(f"{base}out_{m}")
            g.add((out, RDF.type, DICI.ComponentAttributeOutput))
            g.add((out, DICI.isProvidedBy, service))
            g.add((out, DICI.providesOutputEntity, DICI[comp]))
            if attr:
                g.add((out, DICI.providesOutputAttribute, DICI[pascal_case(attr)]))
            if address:
                g.add((out, DICI.atStreamAddress, Literal(address)))
            if output.field:
                g.add((out, DICI.hasResultField, Literal(output.field)))
            if output.unit:
                g.add((out, DICI.hasUnitLabel, Literal(output.unit)))
            if identified_by:
                g.add((out, DICI.identifiedByField, Literal(identified_by)))
            g.add((out, RDFS.label,
                   Literal(f"{comp}.{attr} provided" if attr else f"{comp} provided", lang="en")))

    return g.serialize(format="turtle")
