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


def _rows_to_links(result, link_property: str | None = None) -> list[dict[str, Any]]:
    links = []
    for _, row in result.iterrows():
        links.append({
            "source_uri": row["source"],
            "source_type": _fragment(row["sourceType"]),
            "link_property": link_property or _fragment(row["linkProperty"]),
            "target_uri": row["target"],
            "target_type": _fragment(row["targetType"]),
            "source_label": _fragment(row["source"]),
            "target_label": _fragment(row["target"]),
        })
    return links


def discover_component_links(client) -> list[dict[str, Any]]:
    """Physical component links from the graph, best query first.

    Same fallback chain as the Streamlit loader: direct ``locatedIn``, then
    ``linksComponent`` subproperty reasoning, then the broad relationship
    sweep. Each step is tried only when the previous found nothing."""
    for query, prop in (
        (gq_sysdesc.query_direct_located_in, "locatedIn"),
        (gq_sysdesc.query_links_with_subproperty, None),
        (gq_sysdesc.query_all_component_relationships, None),
    ):
        try:
            result = query(client)
        except Exception:
            continue
        if result is not None and not result.empty:
            links = _rows_to_links(result, prop)
            if links:
                return links
    return []


def match_links_to_requirements(
    discovered_links: list[dict[str, Any]], requirements: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Discovered links per ``CL.Source.Target`` requirement they can fulfil.

    Each match is oriented to the requirement (``suggested_source`` /
    ``suggested_target``): ``locatedIn`` runs child→parent, so the reversed
    direction is checked first, exactly like the Streamlit loader."""
    matched: dict[str, list[dict[str, Any]]] = {}
    for pattern in requirements:
        parts = pattern.split(".")
        if len(parts) < 3:
            continue
        source_type, target_type = parts[1], parts[2]

        matches = [
            {**link, "suggested_source": link["target_uri"], "suggested_target": link["source_uri"]}
            for link in discovered_links
            if link["source_type"] == target_type and link["target_type"] == source_type
        ]
        if not matches:
            matches = [
                {**link, "suggested_source": link["source_uri"], "suggested_target": link["target_uri"]}
                for link in discovered_links
                if link["source_type"] == source_type and link["target_type"] == target_type
            ]
        if matches:
            matched[pattern] = matches
    return matched
