# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Attribute typing / unit / value rules for the Replica Builder editor.

These are the RULES distilled out of the two ~300-line form renderers in
``components/replica_builder/replica_attribute_manager.py``
(``render_attribute_type_fields_constrained`` and
``render_attribute_type_fields_for_edit``). The Streamlit widgets stay in the
component; what an attribute of a given kind may contain — which units are
offered and which is preselected, which currencies and temporal precisions
exist, how a ratio unit splits and joins, when a value counts as a file
reference, and whether a proposed attribute config is complete — lives here,
headless, for any frontend.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# The editor's attribute kinds (the ontology's *Attribute classes minus the
# suffix) — what the add/edit forms know how to render.
ATTRIBUTE_TYPES = (
    "Physical", "Dynamic", "Categorical", "Event", "SimpleCost",
    "UnitBasedCost", "Curve", "Resource", "SimpleValue",
    "CustomPhysicalRatio", "Identifier", "Annotation", "Geospatial",
)

# Currency options offered by the cost forms.
CURRENCY_OPTIONS = ["CHF", "EUR", "USD", "GBP"]

# Temporal precisions for Event attributes (matches the ontology individuals).
TEMPORAL_PRECISIONS = ["Year", "YearMonth", "Date", "DateTime"]

# File-type filters per attribute kind (timeseries pickers / uploaders).
DATA_FILE_TYPES = ['csv', 'json', 'parquet', 'xlsx', 'txt']
GEO_FILE_TYPES = ['geojson', 'json', 'shp', 'kml', 'gpx', 'gml', 'zip']


def default_attribute_type(constraints: Optional[Any]) -> str:
    """The editor kind for an attribute: its ontology constraint's type, else
    the long-standing Physical fallback."""
    if constraints is not None and getattr(constraints, "attribute_type", None):
        return constraints.attribute_type
    return "Physical"


def unit_options(
    available_units: Optional[Sequence[str]],
    default_unit: Optional[str] = None,
    current_unit: Optional[str] = None,
) -> Tuple[List[str], int]:
    """The unit dropdown's options and preselected index.

    Exactly the list-building both forms did inline: start from the loaded
    QUDT units (or just the ontology default when none are loaded), make sure
    the currently-stored unit and the ontology default are present, preselect
    the current unit when editing, else the ontology default. Returns a fresh
    list — the session list is never mutated.
    """
    options = list(available_units or ([] if not default_unit else [default_unit]))
    if current_unit and current_unit not in options:
        options.insert(0, current_unit)
    if default_unit and default_unit not in options:
        options.insert(0, default_unit)
    if current_unit is not None:
        # Edit mode: preselect the stored unit; first option when none stored.
        index = options.index(current_unit) if current_unit in options else 0
    else:
        # Add mode: preselect the ontology default.
        index = options.index(default_unit) if default_unit and default_unit in options else 0
    return options, index


def looks_like_file_reference(value: Any) -> bool:
    """The edit forms' heuristic for SimpleValue/Geospatial: a stored value
    that contains a '.' or '/' is treated as a file reference."""
    return bool(value) and isinstance(value, str) and ('.' in value or '/' in value)


def split_ratio_unit(custom_unit: str, constraints: Optional[Any] = None) -> Tuple[str, str]:
    """Split a CustomPhysicalRatio unit string ("Num/Den") into its parts,
    falling back to the ontology-defined ratio units for missing parts."""
    parts = (custom_unit or "").split('/', 1)
    num = parts[0] if len(parts) > 0 else ''
    den = parts[1] if len(parts) > 1 else ''
    if not num and constraints is not None and getattr(constraints, "ratio_numerator_unit", None):
        num = constraints.ratio_numerator_unit
    if not den and constraints is not None and getattr(constraints, "ratio_denominator_unit", None):
        den = constraints.ratio_denominator_unit
    return num, den


def compose_ratio_unit(numerator_unit: str, denominator_unit: str) -> str:
    """Join ratio unit parts back into the stored "Num/Den" string."""
    return f"{numerator_unit}/{denominator_unit}"


def has_timeseries(attr_data: Mapping[str, Any]) -> bool:
    """Whether a Physical/Dynamic attribute carries any time-series reference."""
    return bool(
        attr_data.get('historic_reference') or
        attr_data.get('future_reference') or
        attr_data.get('live_reference')
    )


# Which key(s) must be present (non-empty) for an attribute config of each
# kind to say anything at all in the generated TTL.
_REQUIRED_KEYS: Dict[str, Tuple[str, ...]] = {
    "Categorical": ("category_value",),
    "Event": ("temporal_value",),
    "Resource": ("data_path",),
    "Identifier": ("identifier_value",),
    "Annotation": ("text",),
    "Curve": ("data_points",),
    "Geospatial": ("value",),
    "SimpleValue": ("value",),
}


def validate_attribute_config(attr_type: str, data: Mapping[str, Any]) -> List[str]:
    """Problems with a proposed attribute config; empty list = acceptable.

    Mirrors what the TTL layer needs, not more: unknown kinds are flagged,
    kind-specific value keys must be present, Event precision (when given)
    must be a known one, numeric kinds must hold numbers.
    """
    problems: List[str] = []

    if attr_type not in ATTRIBUTE_TYPES:
        problems.append(f"Unknown attribute type: {attr_type}")
        return problems

    for key in _REQUIRED_KEYS.get(attr_type, ()):
        if not data.get(key):
            problems.append(f"{attr_type} attribute needs a '{key}'")

    if attr_type == "Event":
        precision = data.get("temporal_precision")
        if precision and precision not in TEMPORAL_PRECISIONS:
            problems.append(f"Unknown temporal precision: {precision}")

    if attr_type in ("SimpleCost", "UnitBasedCost", "CustomPhysicalRatio"):
        value = data.get("value")
        try:
            float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            problems.append(f"{attr_type} attribute needs a numeric 'value'")

    return problems


__all__ = [
    "ATTRIBUTE_TYPES",
    "CURRENCY_OPTIONS",
    "TEMPORAL_PRECISIONS",
    "DATA_FILE_TYPES",
    "GEO_FILE_TYPES",
    "default_attribute_type",
    "unit_options",
    "looks_like_file_reference",
    "split_ratio_unit",
    "compose_ratio_unit",
    "has_timeseries",
    "validate_attribute_config",
]
