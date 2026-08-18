# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Datatype-family registry: which statistics apply to a Set's values.

Family detection is SEMANTIC — the attribute class's base value-type in the
schema graph decides (``rdfs:subClassOf*`` walk), never the spelling of a class
name. A ``SimpleValueAttribute`` subclass is refined by sniffing the actual
literal values (all-numeric → numeric, all-boolean → boolean, else
categorical).

``compute_stats`` returns only the statistics applicable to the family
(open-world: inapplicable statistics are absent, never null/NaN), plus the
distribution bins for the chart the UI draws. A Set whose values mix families
raises :class:`MixedFamilyError` — the materializer fails loudly, it never
coerces.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

NUMERIC = "numeric"
CATEGORICAL = "categorical"
TEMPORAL = "temporal"
BOOLEAN = "boolean"

# Core base value-type → family. The attribute class's ancestor in the schema
# graph selects the row; SIMPLE_VALUE defers to value sniffing.
BASE_TYPE_FAMILY = {
    "PhysicalAttribute": NUMERIC,
    "GeospatialAttribute": NUMERIC,
    "UnitBasedCostAttribute": NUMERIC,
    "SimpleCostAttribute": NUMERIC,
    "CustomPhysicalRatioAttribute": NUMERIC,
    "DynamicAttribute": NUMERIC,
    "CategoricalAttribute": CATEGORICAL,
    "EventAttribute": TEMPORAL,
}
SIMPLE_VALUE_BASE = "SimpleValueAttribute"

# Base types whose values are not scalar and cannot form a Set.
UNSUPPORTED_BASE_TYPES = {"CurveAttribute", "ResourceAttribute"}

_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


class CollectionError(ValueError):
    """A Set cannot be materialized (empty, unsupported type, …)."""


class MixedFamilyError(CollectionError):
    """The values of a Set span more than one datatype family."""


def _as_float(raw: str) -> Optional[float]:
    try:
        v = float(raw)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def sniff_family(values: Sequence[str]) -> str:
    """Family of a SimpleValue attribute, decided by its actual literals."""
    lowered = [str(v).strip().lower() for v in values]
    if all(v in _TRUE | _FALSE for v in lowered):
        return BOOLEAN
    if all(_as_float(v) is not None for v in values):
        return NUMERIC
    return CATEGORICAL


def _histogram(nums: List[float], max_bins: int = 10) -> List[Dict]:
    """Equal-width histogram bins (fewer bins for few values; one bin when the
    values are constant)."""
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return [{"label": f"{lo:g}", "lower": lo, "upper": hi, "frequency": len(nums)}]
    n_bins = min(max_bins, max(1, round(math.sqrt(len(nums)))))
    width = (hi - lo) / n_bins
    bins = [{"label": f"[{lo + i * width:g}, {lo + (i + 1) * width:g})",
             "lower": lo + i * width, "upper": lo + (i + 1) * width, "frequency": 0}
            for i in range(n_bins)]
    bins[-1]["label"] = bins[-1]["label"][:-1] + "]"   # last bin closes the range
    for v in nums:
        i = min(int((v - lo) / width), n_bins - 1)
        bins[i]["frequency"] += 1
    return bins


def compute_stats(family: str, values: Sequence[str]) -> Tuple[Dict, List[Dict]]:
    """Statistics + distribution bins for ``values`` under ``family``.

    Returns ``(stats, bins)`` where ``stats`` maps statistic name (the
    dici_onto datatype-property local name) to a plain Python value, and
    ``bins`` is a list of ``{label, lower?, upper?, frequency}`` dicts.

    Raises :class:`MixedFamilyError` when a value does not belong to the
    family, :class:`CollectionError` on an empty value list.
    """
    if not values:
        raise CollectionError("empty value set — nothing to aggregate")

    if family == NUMERIC:
        nums = []
        for v in values:
            f = _as_float(v)
            if f is None:
                raise MixedFamilyError(
                    f"non-numeric value {v!r} in a numeric set — mixed datatype "
                    f"families are invalid, not coerced")
            nums.append(f)
        stats = {
            "count": len(nums),
            "mean": statistics.fmean(nums),
            "minValue": min(nums),
            "maxValue": max(nums),
            "median": statistics.median(nums),
            "sum": sum(nums),
        }
        if len(nums) > 1:
            stats["standardDeviation"] = statistics.stdev(nums)
        return stats, _histogram(nums)

    if family == BOOLEAN:
        lowered = [str(v).strip().lower() for v in values]
        bad = next((v for v in lowered if v not in _TRUE | _FALSE), None)
        if bad is not None:
            raise MixedFamilyError(f"non-boolean value {bad!r} in a boolean set")
        n_true = sum(1 for v in lowered if v in _TRUE)
        stats = {"count": len(lowered), "distinctCount": len(set(lowered))}
        bins = [{"label": "true", "frequency": n_true},
                {"label": "false", "frequency": len(lowered) - n_true}]
        return stats, bins

    if family == TEMPORAL:
        ordered = sorted(str(v) for v in values)   # ISO-8601 sorts lexically
        stats = {"count": len(ordered),
                 "minValue": ordered[0], "maxValue": ordered[-1]}
        return stats, []

    # categorical (default): frequency table over the raw values
    counts = Counter(str(v) for v in values)
    top = max(counts.values())
    stats = {
        "count": sum(counts.values()),
        "distinctCount": len(counts),
        "mode": sorted(k for k, c in counts.items() if c == top),
    }
    bins = [{"label": k, "frequency": c}
            for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return stats, bins
