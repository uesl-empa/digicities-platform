# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Keep scenarios in step with the service they were built for.

Editing a service (removing a required attribute, dropping a component type)
silently invalidates every scenario tagged ``builtForService`` for it — the
cross-artifact consistency gap. :func:`sync_scenarios_for_service` closes it:
for each such scenario it re-runs the emitter's completeness gate against the
service's CURRENT requirements and

* leaves still-valid scenarios untouched,
* rewrites partially-valid ones thin (same URI/label/service — only the
  incomplete components and their links are dropped), archiving the previous
  file to ``scenarios/_archive/<stem>.<timestamp>.ttl`` first,
* archives + deletes scenarios with nothing valid left,

mirroring every file change into the ``<scenarios>`` named graph (scoped
remove + re-push). The scenario TTL structure is never altered — rewrites go
through :func:`backend.scenario_builder.build_scenario_ttl`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def attach_graph_attributes(client, comps: list[dict[str, Any]]) -> None:
    """Fill in ``attributes``/``nested_properties`` from the workspace graph
    for components that didn't bring their own (a draft only holds
    uri/type/label). Grouped per type so each type is one graph round-trip.
    Client-first twin of the REST layer's helper; failures leave the
    components as they were (the gate then reports them missing)."""
    from backend.explorer import (
        get_component_data_unified,
        get_component_types_with_instances,
        structured_instance_attributes,
    )

    todo: dict[str, list[dict[str, Any]]] = {}
    for c in comps:
        if not c.get("attributes") and not c.get("nested_properties") and c.get("type"):
            todo.setdefault(c["type"], []).append(c)
    if not todo:
        return
    try:
        # The explorer queries key on the display label ("Wind Turbine"); the
        # drafts hold class local names ("WindTurbine") — map between them.
        types_df = get_component_types_with_instances(client)
        label_by_local = {}
        if types_df is not None and not types_df.empty:
            for r in types_df.itertuples():
                local = str(r.componentType).rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                label_by_local[local] = str(r.componentName)
    except Exception:
        return
    for type_name, members in todo.items():
        try:
            _, attrs = get_component_data_unified(client, label_by_local.get(type_name, type_name))
        except Exception:
            continue
        structured = structured_instance_attributes(attrs)
        for c in members:
            found = structured.get(c["uri"])
            if found:
                c["attributes"] = found["attributes"]
                c["nested_properties"] = found["nested_properties"]


def _workspace_id_from_ttl(ttl_text: str, scenario_uri: str) -> str:
    try:
        from rdflib import Graph, Namespace, URIRef
        g = Graph()
        g.parse(data=ttl_text, format="turtle")
        dici = Namespace("https://digicities.info/ontology#")
        for w in g.objects(URIRef(scenario_uri), dici.createdInWorkspace):
            return str(w)
    except Exception:
        pass
    return ""


def sync_scenarios_for_service(storage, client, service_file: str,
                               *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Re-validate every scenario built for the service in ``service_file``
    (workspace-relative, e.g. ``services/WindSvc.yaml``) against its current
    requirements. Returns a report::

        {"service": name,
         "scenarios": [{"scenario": rel, "action": "unchanged"|"rewritten"|
                        "removed"|"skipped", "detail": str,
                        "dropped": [component labels]}]}

    Graph updates are best-effort (a failed push is reported in ``detail``,
    the file change stands); parse failures skip the scenario rather than
    taking the sync down.
    """
    import yaml

    from backend.scenario_builder import build_scenario_ttl
    from backend.scenario_builder.emitter import (
        get_filtered_components_for_ttl,
        get_filtered_links_for_ttl,
        resolve_nested_attribute_requirement,
    )
    from backend.scenario_builder.publish import (
        push_scenario_to_graph,
        remove_scenario_from_graph,
    )
    from backend.scenario_builder.reload import draft_from_ttl
    from backend.scenario_builder.requirements import extract_required_attributes_enhanced

    template = yaml.safe_load(storage.read_text(service_file)) or {}
    service_name = template.get("service_name") or ""
    required, _nested = extract_required_attributes_enhanced(template)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")

    report: dict[str, Any] = {"service": service_name, "scenarios": []}
    if not service_name:
        return report

    for rel in sorted(storage.glob("scenarios/*.ttl")):
        entry: dict[str, Any] = {"scenario": rel, "action": "unchanged", "detail": "",
                                 "dropped": []}
        try:
            text = storage.read_text(rel)
            draft = draft_from_ttl(text)
        except Exception as exc:
            entry.update(action="skipped", detail=f"unreadable ({type(exc).__name__})")
            report["scenarios"].append(entry)
            continue
        if draft.get("service_name") != service_name:
            continue                          # built for another service (or none)

        comps = [{"uri": c["uri"], "type": c.get("type"), "label": c.get("label") or c["uri"],
                  "attributes": {}, "nested_properties": {}}
                 for c in draft.get("components", [])]
        attach_graph_attributes(client, comps)
        # URI/label are synthetic identity attributes (templates reference
        # them as Type.URI) — same injection the REST validation does.
        for c in comps:
            c["attributes"].setdefault("URI", {"value": c["uri"]})
            c["attributes"].setdefault("label", {"value": c["label"]})

        kept = get_filtered_components_for_ttl(comps, required)
        kept_links = get_filtered_links_for_ttl(draft.get("links", []), kept)
        if len(kept) == len(comps) and len(kept_links) == len(draft.get("links", [])):
            report["scenarios"].append(entry)
            continue

        # Something must go: archive the current file first, always.
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        archive_rel = f"scenarios/_archive/{stem}.{stamp}.ttl"
        storage.write_text(archive_rel, text)

        scenario_uri = draft.get("scenario_uri") or ""
        for c in comps:
            if c["uri"] not in {k["uri"] for k in kept}:
                entry["dropped"].append(c["label"])
                missing = [r for r in required.get(c["type"] or "", [])
                           if not _safe_resolve(resolve_nested_attribute_requirement, c, r)]
                if missing:
                    entry["dropped"][-1] += f" (missing {', '.join(missing)})"

        if not kept:
            storage.delete(rel)
            entry.update(action="removed",
                         detail=f"no component satisfies the service any more; archived to {archive_rel}")
            try:
                if scenario_uri:
                    remove_scenario_from_graph(client, scenario_uri)
            except Exception as exc:
                entry["detail"] += f"; graph cleanup failed ({type(exc).__name__})"
            report["scenarios"].append(entry)
            continue

        # Rewrite thin: same URI/label/service/description, kept set only.
        links = [{"source": scenario_uri if l["source"] == "scenario" else l["source"],
                  "target": l["target"], "link_type": l.get("link_type") or "scenario_automatic"}
                 for l in kept_links]
        new_ttl = build_scenario_ttl(
            scenario_name=draft.get("scenario_name") or stem,
            workspace_id=_workspace_id_from_ttl(text, scenario_uri),
            components=[c["uri"] for c in kept],
            links=links,
            service_name=service_name,
            description=draft.get("description"),
            scenario_uri=scenario_uri or None)
        storage.write_text(rel, new_ttl if new_ttl.endswith("\n") else new_ttl + "\n")
        entry.update(action="rewritten",
                     detail=f"kept {len(kept)}/{len(comps)} components; previous version "
                            f"archived to {archive_rel}")
        try:
            if scenario_uri:
                remove_scenario_from_graph(client, scenario_uri)
            push_scenario_to_graph(client, new_ttl)
        except Exception as exc:
            entry["detail"] += f"; graph update failed ({type(exc).__name__})"
        report["scenarios"].append(entry)

    return report


def _safe_resolve(resolver, component, requirement) -> Any:
    try:
        return resolver(component, requirement)
    except Exception:
        return None


__all__ = ["sync_scenarios_for_service", "attach_graph_attributes"]
