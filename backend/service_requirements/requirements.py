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

from typing import Iterable, Sequence, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

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
) -> str:
    """Serialize a service's requirements as Turtle.

    ``requirements`` yields (component, attribute names) pairs — one
    ``ComponentAttributeRequirement`` per attribute; ``links`` yields
    (domain, range) component pairs — one ``ComponentComponentRequirement``
    each. ``base`` is the URI prefix requirement nodes live under (ends with
    ``/``, e.g. ``https://digicities.info/proj/<ws>/services/``). Requirement
    nodes are numbered ``req_1..req_n`` across both kinds, attribute
    requirements first.
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

    return g.serialize(format="turtle")
