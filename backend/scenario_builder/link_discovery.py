# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Graph-derived link suggestions for the Scenario Builder, headless.

The system_description graph (and classes_and_attributes) records physical
relationships between components — ``locatedIn`` and other
``linksComponent`` subproperties. The Streamlit builder offered these as
one-click link suggestions per ``CL.Source.Target`` requirement
(graphdb_system_description_loader.py); this is that logic moved behind the
backend seam. The SPARQL itself already lives in
``backend.graphdb.queries.system_description``.
"""
from __future__ import annotations

from typing import Any

from backend.graphdb.queries import system_description as gq_sysdesc


def _fragment(uri: str) -> str:
    if "#" in uri:
        return uri.split("#")[-1]
    if "/" in uri:
        return uri.rstrip("/").split("/")[-1]
    return uri


def _rows_to_links(result) -> list[dict[str, Any]]:
    links = []
    for _, row in result.iterrows():
        links.append({
            "source_uri": row["source"],
            "source_type": _fragment(row["sourceType"]),
            "link_property": _fragment(row["linkProperty"]),
            "target_uri": row["target"],
            "target_type": _fragment(row["targetType"]),
            "source_label": _fragment(row["source"]),
            "target_label": _fragment(row["target"]),
        })
    return links


def discover_component_links(client) -> list[dict[str, Any]]:
    """Component links from the graph, every kind at once.

    The place links (located in / at, ``LOCATION_PREDICATES``) and every other
    ``linksComponent`` subproperty (a flow's ``hasSource`` / ``hasDestination``,
    its carrier) are read together: a workspace with sites nearly always has
    place links, and stopping at them hid every other link. The broad
    relationship sweep is the fallback when neither finds anything. Every link
    carries the predicate it was found by."""
    links: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for queries in (
        (gq_sysdesc.query_direct_located_in, gq_sysdesc.query_links_with_subproperty),
        (gq_sysdesc.query_all_component_relationships,),
    ):
        for query in queries:
            try:
                result = query(client)
            except Exception:
                continue
            if result is None or result.empty:
                continue
            for link in _rows_to_links(result):
                key = (link["source_uri"], link["source_type"], link["link_property"],
                       link["target_uri"], link["target_type"])
                if key not in seen:
                    seen.add(key)
                    links.append(link)
        if links:
            return links
    return []


def match_links_to_requirements(
    discovered_links: list[dict[str, Any]], requirements: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Discovered links per ``CL.Source.Target`` requirement they can fulfil.

    Each match is oriented to the requirement (``suggested_source`` /
    ``suggested_target``): a link is offered whichever way it is stored (place
    links run child→parent, a ``CL.Parent.Child`` requirement the other way)."""
    matched: dict[str, list[dict[str, Any]]] = {}
    for pattern in requirements:
        parts = pattern.split(".")
        if len(parts) < 3:
            continue
        source_type, target_type = parts[1], parts[2]

        forward = [
            {**link, "suggested_source": link["source_uri"], "suggested_target": link["target_uri"]}
            for link in discovered_links
            if link["source_type"] == source_type and link["target_type"] == target_type
        ]
        reversed_ = [
            {**link, "suggested_source": link["target_uri"], "suggested_target": link["source_uri"]}
            for link in discovered_links
            if link["source_type"] == target_type and link["target_type"] == source_type
        ]
        matches = _one_per_pair(forward + reversed_, len(forward))
        if matches:
            matched[pattern] = matches
    return matched


def _one_per_pair(matches: list[dict[str, Any]], n_forward: int) -> list[dict[str, Any]]:
    """One suggestion per source and target. A pair is often found by its own
    predicate, by its inverse and by ``linksComponent`` above both: a named
    predicate wins over ``linksComponent``, then the one running the
    requirement's way (the first ``n_forward``) over its inverse."""
    def rank(i: int, m: dict[str, Any]) -> tuple[int, int]:
        return (m["link_property"] == "linksComponent", i >= n_forward)

    best: dict[tuple[str, str], tuple[tuple[int, int], dict[str, Any]]] = {}
    for i, m in enumerate(matches):
        pair = (m["suggested_source"], m["suggested_target"])
        r = rank(i, m)
        if pair not in best or r < best[pair][0]:
            best[pair] = (r, m)
    return [m for _, m in best.values()]
