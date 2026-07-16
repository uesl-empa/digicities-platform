# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""CONSTRUCT / graph-export helpers.

Pure, UI-independent helpers to pull whole named graphs (or arbitrary CONSTRUCT
results) out of the triplestore as Turtle or as an rdflib Graph. The query URL is
backend-aware (via ``client._query_url``), so these work on Fuseki, GraphDB,
RDF4J, etc. — unlike the older inline code that hard-coded GraphDB's
``/repositories/<repo>`` path.
"""

from __future__ import annotations

from typing import Optional

import requests
import rdflib


def construct_ttl(client, query: str, timeout: int = 60) -> Optional[str]:
    """Run a CONSTRUCT query and return the result as Turtle text, or None.

    Uses the client's backend-aware query URL and a ``text/turtle`` Accept
    header (CONSTRUCT results aren't SPARQL-JSON). Never raises.
    """
    if client is None:
        return None
    try:
        url = f"{client._query_url(query)}&infer=True"
        client.check_access_token_time_valid(renew=True)
        headers = {"Accept": "text/turtle"}
        if getattr(client, "access_token", None):
            headers["Authorization"] = client.access_token
        response = requests.get(url, headers=headers, timeout=timeout)
        if response is not None and response.status_code == 200:
            # Turtle is always UTF-8. requests defaults a charset-less text/*
            # response to ISO-8859-1, which mangles non-ASCII (e.g. an em-dash
            # in a label), so decode the body as UTF-8 explicitly.
            response.encoding = "utf-8"
            return response.text
        code = getattr(response, "status_code", "?")
        print(f"[graphdb.queries.graph_io] CONSTRUCT returned HTTP {code}")
        return None
    except Exception as exc:
        print(f"[graphdb.queries.graph_io] CONSTRUCT failed: {exc}")
        return None


def construct_named_graph(client, graph_iri: str) -> Optional[rdflib.Graph]:
    """CONSTRUCT every triple in a named graph and return it as an rdflib Graph.

    ``graph_iri`` may be bare or angle-bracketed. Returns None on failure.
    """
    iri = graph_iri.strip()
    if iri.startswith("<") and iri.endswith(">"):
        iri = iri[1:-1]
    query = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{iri}> {{ ?s ?p ?o }} }}"
    ttl = construct_ttl(client, query)
    if ttl is None:
        return None
    try:
        graph = rdflib.Graph()
        graph.parse(data=ttl, format="turtle")
        return graph
    except Exception as exc:
        print(f"[graphdb.queries.graph_io] could not parse CONSTRUCT result for <{iri}>: {exc}")
        return None
