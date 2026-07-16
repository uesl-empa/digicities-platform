# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Headless scenario-TTL builder.

Backend counterpart to the Streamlit Scenario Builder's ``generate_full_ttl()``
(``apps/streamlit/components/scenario_builder/scenario_builder_summary.py``),
with **no ``st.session_state`` dependency** — so agents, scripts and tests can
produce a valid scenario TTL headlessly. The onboarding kit's Stage-4 gap.

It emits the same structure the rest of the pipeline consumes:
- provisioning loads ``scenarios/*.ttl`` into ``<http://scenarios>``;
- the API-submission converter walks the ``dici_onto:ComponentLink`` edges
  (``CL.<From>.<To>`` in a service template) to build the nested payload.

Predicate spellings (incl. the historical ``linksInputyEntityTo`` typo) match
the UI generator and the shipped demo scenarios verbatim, so the output is a
drop-in for what the UI writes.

Example
-------
>>> from backend.scenario_builder import build_scenario_ttl, scenario_uri_for
>>> proj = "https://digicities.info/proj/my-ws"
>>> sc = scenario_uri_for("my-ws", "My Scenario")
>>> ttl = build_scenario_ttl(
...     scenario_name="My Scenario", workspace_id="my-ws",
...     service_name="demo_energy_simulator",
...     components=[f"{proj}/Location/TownCentre", f"{proj}/Building/MFH_1"],
...     links=[(sc, f"{proj}/Location/TownCentre"),
...            (f"{proj}/Location/TownCentre", f"{proj}/Building/MFH_1")])
>>> # ctx.storage.write_text(save path) or use save_scenario_ttl(ctx.storage, ...)
"""
from __future__ import annotations

from typing import Optional, Sequence, Union

DICI_NS = "https://digicities.info/ontology#"

Component = Union[str, dict]          # a URI, or {"uri":.., "type"?:.., "label"?:..}
Link = Union[tuple, list, dict]       # (source, target) or {"source":.., "target":.., "link_type"?:..}


def scenario_uri_for(workspace_id: str, scenario_name: str) -> str:
    """The canonical scenario IRI, matching the UI convention (spaces/slashes → ``_``)."""
    safe = scenario_name.replace(" ", "_").replace("/", "_")
    return f"https://digicities.info/proj/{workspace_id}/{safe}"


def _esc(s) -> str:
    """Escape a value for a TTL double-quoted literal."""
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r"))


def build_scenario_ttl(
    scenario_name: str,
    workspace_id: str,
    components: Sequence[Component],
    links: Sequence[Link],
    *,
    service_name: Optional[str] = None,
    description: Optional[str] = None,
    scenario_uri: Optional[str] = None,
    link_type: str = "scenario_automatic",
) -> str:
    """Build a scenario TTL string that references existing replica instances.

    Args:
        scenario_name: Human label; also derives the scenario IRI.
        workspace_id: Owning workspace id (recorded via ``dici_onto:createdInWorkspace``).
        components: instances to include. Each is either a URI string (emits just
            ``<uri> dici_onto:usedInScenario <scenario>``) or a dict
            ``{"uri":.., "type"?:.., "label"?:..}`` (also re-declares the class/label).
        links: directed edges as ``(source_uri, target_uri)`` tuples or
            ``{"source":.., "target":.., "link_type"?:..}`` dicts. Each becomes a
            ``dici_onto:ComponentLink`` with ``hasInputEntity=source`` and
            ``linksInputyEntityTo=target``. Attach a top-level component to the
            scenario by using the scenario IRI as the source.
        service_name: If set, records ``dici_onto:builtForService`` so the API
            submission convert tab can match this scenario to that service.
        description: Optional ``dcterms:description``.
        scenario_uri: Override the derived scenario IRI.
        link_type: Default ``dici_onto:linkType`` for tuple links.

    Returns:
        A complete Turtle document (str). Save it under the workspace
        ``scenarios/`` dir (see :func:`save_scenario_ttl`).
    """
    sc = scenario_uri or scenario_uri_for(workspace_id, scenario_name)
    desc = description if description is not None else f"Scenario built in workspace {workspace_id}"

    lines = [
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        f"<{sc}> a dici_onto:Scenario ;",
        f'    rdfs:label "{_esc(scenario_name)}" ;',
        f'    dcterms:description "{_esc(desc)}" ;',
    ]
    if service_name:
        lines.append(f'    dici_onto:builtForService "{_esc(service_name)}" ;')
    lines.append(f'    dici_onto:createdInWorkspace "{_esc(workspace_id)}" .')
    lines.append("")

    # Components → usedInScenario (+ optional class/label re-declaration).
    for comp in components:
        if isinstance(comp, str):
            uri, ctype, label = comp, None, None
        else:
            uri, ctype, label = comp["uri"], comp.get("type"), comp.get("label")
        if ctype:
            lines.append(f"<{uri}> a dici_onto:{ctype} ;")
            if label:
                lines.append(f'    rdfs:label "{_esc(label)}" ;')
            lines.append(f"    dici_onto:usedInScenario <{sc}> .")
        else:
            lines.append(f"<{uri}> dici_onto:usedInScenario <{sc}> .")
    lines.append("")

    # Links → dici_onto:ComponentLink (drives the nested payload in conversion).
    for i, link in enumerate(links, start=1):
        if isinstance(link, dict):
            src, tgt, lt = link["source"], link["target"], link.get("link_type", link_type)
        else:
            src, tgt, lt = link[0], link[1], link_type
        lines += [
            f"<{sc}/ComponentLink_{i}> a dici_onto:ComponentLink ;",
            f"    dici_onto:hasInputEntity <{src}> ;",
            f"    dici_onto:linksInputyEntityTo <{tgt}> ;",
            f'    dici_onto:linkType "{_esc(lt)}" ;',
            f"    dici_onto:usedInScenario <{sc}> .",
            "",
        ]
    return "\n".join(lines)


def save_scenario_ttl(storage, scenario_name: str, ttl: str) -> str:
    """Write ``ttl`` to the workspace ``scenarios/<safe_name>.ttl`` via a
    WorkspaceStorage handle (``ctx.storage``). Returns the workspace-relative path."""
    safe = scenario_name.replace(" ", "_").replace("/", "_")
    rel = f"scenarios/{safe}.ttl"
    storage.write_text(rel, ttl)
    return rel


__all__ = ["build_scenario_ttl", "save_scenario_ttl", "scenario_uri_for", "DICI_NS"]
