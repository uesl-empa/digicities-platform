# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# backend/assumptions/thin_scenario_ttl.py
"""
Thin-scenario TTL builder for the Assumptions module.

An assumption produces a *what-if variant* of a baseline that references the
canonical replica components. Rather than duplicating every component and
re-serialising every attribute (which silently dropped resource data paths,
curves, unit labels, …), we emit a **thin scenario**: the exact shape the
Scenario Builder and hand-authored scenarios use, and which
``backend.graphdb.queries.scenarios.materialize_scenario_graphs`` consumes.

Shape (mirrors demo_workspaces/energy-simulation/scenarios/energy_sim_retrofit.ttl):

    <scn> a dici_onto:Scenario ; rdfs:label … ; dici_onto:basedOn <baseline> ;
          dici_onto:modifiedComponents "N"^^xsd:integer .

    # anchor every component (changed AND unchanged) to the scenario so the
    # materialiser reaches it and inherits its replica attributes verbatim
    <comp> dici_onto:usedInScenario <scn> .

    # one override node per CHANGED attribute — a fresh URI carrying the new
    # value, typed canonically, superseding the replica attribute
    <comp/Attr_override> a dici_onto:Attr, dici_onto:PhysicalAttribute ;
        qudt:value "…"^^xsd:decimal ; qudt:unit <…> ; dici_onto:hasUnitLabel "…" ;
        dici_onto:supersedesAttribute <comp/Attr> ;
        dici_onto:usedInScenario <scn> .

Unchanged attributes are NOT emitted — they inherit from the replica, so nothing
is lost. Attribute serialisation mirrors the single source of truth,
``backend.replica_builder.utils.ttl_attribute_helpers.generate_attribute_ttl``.

Requires the baseline to reference canonical replica URIs (the normal workflow:
baselines come from the Scenario Builder or thin hand-authored scenarios). A
component/attribute whose URI is not in the replica graph simply won't resolve
overrides at materialisation time — the same contract every thin scenario has.
"""

from typing import Dict, List

_PREFIXES = [
    "@prefix dici_onto: <https://digicities.info/ontology#> .",
    "@prefix qudt: <http://qudt.org/schema/qudt/> .",
    "@prefix unit: <http://qudt.org/vocab/unit/> .",
    "@prefix cur: <http://qudt.org/vocab/currency/> .",
    "@prefix dcterms: <http://purl.org/dc/terms/> .",
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
]

# Attribute-type families, matched to the canonical serialiser's predicates.
_QUDT_VALUE_TYPES = {
    "PhysicalAttribute", "DynamicAttribute",
    "SimpleCostAttribute", "UnitBasedCostAttribute",
    "CustomPhysicalRatioAttribute",
}
_ATTRVALUE_TYPES = {"GeospatialAttribute", "SimpleValueAttribute"}
_UNIT_TYPES = {"PhysicalAttribute", "DynamicAttribute", "UnitBasedCostAttribute"}
_CURRENCY_TYPES = {"SimpleCostAttribute", "UnitBasedCostAttribute"}


def _fmt_decimal(value) -> str:
    """Format a numeric value for an xsd:decimal literal, or None if non-numeric."""
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    return f"{int(f)}.0" if f.is_integer() else f"{f}"


def _clean_class(name: str) -> str:
    """Strip separators from a name so it is a legal TTL local-name / class."""
    return str(name).replace(" ", "").replace("-", "").replace("_", "").replace(".", "")


def _esc(s) -> str:
    """Escape a Python value for a TTL double-quoted string literal."""
    s = str(s)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def _override_lines(attr_name: str, attr: Dict, scenario_uri: str) -> List[str]:
    """Serialise one override attribute node, or [] if the type is unsupported.

    Mirrors ``ttl_attribute_helpers.generate_attribute_ttl`` for the scalar and
    categorical families an assumption can modify; other types (Curve, Event,
    Resource, …) are never numerically modified, so we skip them and let the
    replica value stand rather than emit something lossy.
    """
    override_uri = attr["uri"]
    original_uri = attr.get("original_uri")
    if not original_uri:
        return []

    attr_type = attr.get("attribute_type", "PhysicalAttribute")
    category = attr.get("category", "")
    attr_class = _clean_class(attr.get("attr_class", attr_name))

    types = [f"dici_onto:{attr_class}"]
    props: List[str] = []

    is_categorical = attr_type == "CategoricalAttribute" or category == "categorical"

    if is_categorical:
        types.append("dici_onto:CategoricalAttribute")
        value_class = _clean_class(attr.get("category_value") or attr.get("value") or "")
        if not value_class:
            return []
        types.append(f"dici_onto:{value_class}")
    else:
        types.append(f"dici_onto:{attr_type}")

        if attr_type in _QUDT_VALUE_TYPES:
            dec = _fmt_decimal(attr.get("value"))
            if dec is not None:
                props.append(f'qudt:value "{dec}"^^xsd:decimal')
            else:
                props.append(f'qudt:value "{_esc(attr.get("value", ""))}"^^xsd:string')
        elif attr_type in _ATTRVALUE_TYPES:
            dec = _fmt_decimal(attr.get("value"))
            if dec is not None:
                props.append(f'dici_onto:hasAttributeValue "{dec}"^^xsd:decimal')
            else:
                props.append(f'dici_onto:hasAttributeValue "{_esc(attr.get("value", ""))}"^^xsd:string')
        else:
            # Unsupported scalar family — leave the replica value untouched.
            return []

        unit = attr.get("unit")
        if unit and unit not in ("", "dimensionless", "category", "text") and attr_type in _UNIT_TYPES:
            props.append(f"qudt:unit <http://qudt.org/vocab/unit/{unit}>")
            props.append(f'dici_onto:hasUnitLabel "{_esc(unit)}"^^xsd:string')

        if attr_type in _CURRENCY_TYPES and attr.get("currency"):
            props.append(f"dici_onto:currency cur:{_clean_class(attr['currency'])}")

    props.append(f"dici_onto:supersedesAttribute <{original_uri}>")
    props.append(f"dici_onto:usedInScenario <{scenario_uri}>")

    head = f"<{override_uri}> a " + ", ".join(types)
    lines = [head + " ;"]
    for p in props[:-1]:
        lines.append(f"    {p} ;")
    lines.append(f"    {props[-1]} .")
    return lines


def build_thin_scenario_ttl(scenario_data: Dict) -> str:
    """Build a thin-scenario Turtle document from an assumptions engine result.

    ``scenario_data`` is what ``assumption_engine`` / ``manual_modification_engine``
    return: a ``scenario_name``/``namespace`` plus a ``components`` list whose
    modified attributes carry ``is_modified`` + ``original_uri`` markers.
    """
    scenario_name = scenario_data["scenario_name"]
    namespace = scenario_data.get("namespace", "https://digicities.info/proj/REFORMERS")
    scenario_uri = f"{namespace}/{scenario_name.replace(' ', '_')}"
    components = scenario_data.get("components", [])

    lines: List[str] = list(_PREFIXES) + ["", "# Scenario declaration"]

    scn_props = [f'rdfs:label "{_esc(scenario_name)}"']
    scn_props.append('dcterms:description "Scenario generated by the Assumptions module"')
    based_on = scenario_data.get("based_on")
    if based_on:
        scn_props.append(f"dici_onto:basedOn <{based_on}>")
    assumption = scenario_data.get("assumption") or {}
    if assumption:
        scn_props.append(f'dici_onto:assumptionApplied "{_esc(assumption.get("name", "Unknown"))}"')
        scn_props.append(f'dici_onto:assumptionType "{_esc(scenario_data.get("type", "single"))}"')
    workspace = scenario_data.get("workspace")
    if workspace:
        scn_props.append(f'dici_onto:createdInWorkspace "{_esc(workspace)}"')
    service = scenario_data.get("service")
    if service:
        scn_props.append(f'dici_onto:builtForService "{_esc(service)}"')
    scn_props.append(f'dici_onto:modifiedComponents "{scenario_data.get("modified_count", 0)}"^^xsd:integer')

    lines.append(f"<{scenario_uri}> a dici_onto:Scenario ;")
    for p in scn_props[:-1]:
        lines.append(f"    {p} ;")
    lines.append(f"    {scn_props[-1]} .")
    lines.append("")

    # Anchor each real component to the scenario (materialiser reaches them by
    # tag). The loader indexes every rdf:type, so attribute / link / scenario /
    # value-class nodes also arrive here as "components"; they carry no
    # attributes, so anchoring only components that own attributes (deduped)
    # keeps the scenario to its genuine components.
    lines.append("# Component anchors (attributes inherit from the replica)")
    override_blocks: List[List[str]] = []
    anchored: set = set()
    for comp in components:
        real_attrs = {k: v for k, v in comp.get("attributes", {}).items()
                      if k not in ("URI", "label") and isinstance(v, dict)}
        if not real_attrs:
            continue
        anchor = comp.get("derived_from") or comp.get("uri")
        if not anchor or anchor in anchored:
            continue
        anchored.add(anchor)
        lines.append(f"<{anchor}> dici_onto:usedInScenario <{scenario_uri}> .")
        for attr_name, attr in real_attrs.items():
            if attr.get("is_modified"):
                block = _override_lines(attr_name, attr, scenario_uri)
                if block:
                    override_blocks.append(block)
    lines.append("")

    # Override attribute nodes.
    if override_blocks:
        lines.append("# Attribute overrides")
        for block in override_blocks:
            lines.extend(block)
        lines.append("")

    # Preserve baseline structure (ComponentLinks), re-anchored to this scenario.
    # The chain root must be THIS scenario: the baseline's first hop is rooted at
    # the baseline scenario URI, so re-point any endpoint that equals based_on to
    # the new scenario (matching energy_sim_retrofit.ttl). Downstream traversal
    # (the API-submission converter) follows these links to nest components.
    links = scenario_data.get("component_links", [])
    if links:
        lines.append("# Component links")
        for i, link in enumerate(links, start=1):
            props = link.get("properties", link)
            src = props.get("hasInputEntity") or link.get("source")
            tgt = props.get("linksInputyEntityTo") or link.get("target")
            if not (src and tgt):
                continue
            if based_on and src == based_on:
                src = scenario_uri
            if based_on and tgt == based_on:
                tgt = scenario_uri
            link_uri = f"{scenario_uri}/ComponentLink_{i}"
            lines.append(f"<{link_uri}> a dici_onto:ComponentLink ;")
            lines.append(f"    dici_onto:hasInputEntity <{src}> ;")
            lines.append(f"    dici_onto:linksInputyEntityTo <{tgt}> ;")
            lines.append(f"    dici_onto:usedInScenario <{scenario_uri}> .")
        lines.append("")

    return "\n".join(lines)
