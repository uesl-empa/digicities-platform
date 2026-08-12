# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""What counts as "no unit".

Several readers turn a ``qudt:Unit`` IRI into a string for display or for
re-emission. Each of them independently has to answer the same question first:
is this actually a unit, or an absence dressed up as one?

Absences reach the graph in more than one shape:

* ``unit:None`` — the Excel→TTL ingestion interpolated a missing unit straight
  into the IRI for years, so existing workspaces are full of this. It expands to
  ``http://qudt.org/vocab/unit/None``, which resolves to nothing.
* ``unit:`` / the bare namespace — the Replica Builder emits this when a unit
  field is left empty. Naive local-name extraction renders it as the word
  ``unit``.
* the literal strings ``None`` / ``null`` / ``nan``, from a value that went
  through ``str()`` somewhere upstream.

A dimensionless quantity (a coefficient, a ratio, a thrust curve's Y axis) has no
unit *legitimately*, so these must render as nothing at all — never as a made-up
unit, and never as the word "None".
"""

from __future__ import annotations

QUDT_UNIT_NS = "http://qudt.org/vocab/unit/"

# Compared lower-cased, after stripping whitespace.
_MISSING = {
    "", "none", "null", "nan", "n/a",
    "unit:", "unit:none", "unit",
    QUDT_UNIT_NS, QUDT_UNIT_NS.lower() + "none",
}


def is_missing_unit(unit_uri: str | None) -> bool:
    """True when a unit IRI/CURIE carries no actual unit."""
    if unit_uri is None:
        return True
    return str(unit_uri).strip().lower() in _MISSING


def unit_local_name(unit_uri: str | None) -> str:
    """The QUDT unit code from an IRI or CURIE, or '' when there is no unit.

    Returns the code as authored (``KiloW-HR``), not a display abbreviation, so
    the result round-trips back into a valid ``unit:<code>`` IRI. Callers that
    want a friendlier label should map the code afterwards.
    """
    if is_missing_unit(unit_uri):
        return ""
    raw = str(unit_uri).strip()
    code = raw[len("unit:"):] if raw.startswith("unit:") else raw.rstrip("/").rsplit("/", 1)[-1]
    return "" if is_missing_unit(code) else code
