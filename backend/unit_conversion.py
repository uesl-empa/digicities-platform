# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Convert a value into the unit a service asks for.

A service contract may name the unit a field must be in
(``CapMax: {ref: EnergyConverter.CapMax, unit: KiloW}``). Every value in a
replica carries its own QUDT unit, so the platform converts; a service never
has to guess what a number means.

Factors come from QUDT (data/ontology/imports/qudt_conversions.json, built by
scripts/build_qudt_conversions.py): SI value = (value + offset) * multiplier.
Two units convert into each other only when their dimension vectors are the
same. Anything else is refused, with the reason, never sent as a wrong number:
energy where power is asked, an unknown unit, a value that states no unit when
the field asks for one with a dimension, a different currency (there are no
exchange rates).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from backend.units import is_missing_unit, unit_local_name

# A quantity with no dimension (a share, an efficiency) may legitimately state
# no unit; one that asks for a dimensionless unit accepts it as written.
DIMENSIONLESS = "A0E0L0I0M0H0T0D1"


class UnitRefused(ValueError):
    """The value cannot be given in the unit asked for; the message says why."""


def _table_path() -> Path:
    base = os.environ.get("ONTOLOGY_DIR")
    if base and (Path(base) / "imports" / "qudt_conversions.json").is_file():
        return Path(base) / "imports" / "qudt_conversions.json"
    return Path(__file__).resolve().parents[1] / "data" / "ontology" / "imports" / "qudt_conversions.json"


@lru_cache(maxsize=1)
def _units() -> dict:
    return json.loads(_table_path().read_text(encoding="utf-8"))["units"]


def unit_factor(code: str) -> Optional[Tuple[float, float, str]]:
    """``(multiplier, offset, dimension vector)`` for a QUDT unit code, or None."""
    row = _units().get(code)
    return (row[0], row[1], row[2]) if row else None


def _known(code: str, role: str) -> Tuple[float, float, str]:
    row = unit_factor(code)
    if row is None:
        raise UnitRefused(f"{role} unit {code} is not a QUDT unit the platform can convert")
    return row


def convert(value: float, unit: Optional[str], to: str) -> float:
    """``value`` given in ``unit`` (a QUDT code, IRI or CURIE), in ``to``."""
    to = unit_local_name(to)
    # Already in the unit asked for: nothing to convert, whether or not QUDT knows it.
    if not is_missing_unit(unit) and unit_local_name(unit) == to:
        return value
    mt, ot, dt = _known(to, "the asked")
    if is_missing_unit(unit):
        # A share with no unit is a plain number: fine as UNITLESS, ambiguous as PERCENT.
        if dt == DIMENSIONLESS and mt == 1 and ot == 0:
            return value
        raise UnitRefused(f"the value states no unit, so it cannot be given in {to}")
    code = unit_local_name(unit)
    mf, of, df = _known(code, "the value's")
    if df != dt:
        raise UnitRefused(f"{code} is a different kind of quantity from {to}")
    return (value + of) * mf / mt - ot


def convert_cost(value: float, per: Optional[str], currency: Optional[str],
                 to_per: Optional[str], to_currency: Optional[str]) -> float:
    """A cost per ``per`` in ``currency``, as a cost per ``to_per`` in ``to_currency``.

    Only the "per" unit converts, inversely (0.1 CHF per kWh is 100 CHF per
    MWh). A currency never converts: the platform holds no exchange rates.
    """
    if to_currency:
        have = unit_local_name(currency) if currency else ""
        if not have:
            raise UnitRefused(f"the cost states no currency, and {to_currency} is asked")
        if have.rsplit(":", 1)[-1] != to_currency:
            raise UnitRefused(f"the cost is in {have}, not {to_currency}; "
                              "the platform has no exchange rates")
    if not to_per:
        return value
    to_per = unit_local_name(to_per)
    if not is_missing_unit(per) and unit_local_name(per) == to_per:
        return value
    mt, ot, dt = _known(to_per, "the asked")
    if is_missing_unit(per):
        raise UnitRefused(f"the cost states no unit it is per, and per {to_per} is asked")
    code = unit_local_name(per)
    mf, of, df = _known(code, "the value's")
    if df != dt or of or ot:
        raise UnitRefused(f"a cost per {code} cannot be given per {to_per}")
    return value * mt / mf


def same_unit(unit: Optional[str], to: str) -> bool:
    """True when a value in ``unit`` needs no conversion to be in ``to``
    (the same code, or another name with the same factor)."""
    to = unit_local_name(to)
    if is_missing_unit(unit):
        row = unit_factor(to)
        return row is not None and row[2] == DIMENSIONLESS and row[0] == 1 and row[1] == 0
    code = unit_local_name(unit)
    if code == to:
        return True
    a, b = unit_factor(code), unit_factor(to)
    return a is not None and b is not None and a == b
