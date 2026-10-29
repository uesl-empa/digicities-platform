# Imports

External vocabularies bundled here for offline lookup by the platform's UI.

## `qudt_units.txt`

A flat list of QUDT unit short codes (e.g. `KiloW-HR`, `M2`, `CHF`) used to populate the unit dropdowns in the Replica Builder's attribute forms.

**Source:** [QUDT — Quantities, Units, Dimensions, and Data Types in OWL/XML](https://www.qudt.org/) (QUDT Project, maintained by Topquadrant Inc.)

**License:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)

QUDT is freely redistributable with attribution. If you derive a new units file from QUDT, retain this README and the attribution above.

## Refreshing

The full QUDT distribution is at <https://github.com/qudt/qudt-public-repo>. To regenerate `qudt_units.txt` from a newer QUDT release, dump every `qudt:Unit` IRI and strip the namespace prefix — the file is one short-code per line.

## `qudt_conversions.json`

For each QUDT unit: its multiplier and offset to the SI unit of its dimension
(SI value = (value + offset) × multiplier) and its dimension vector. The platform
uses it to send a value in the unit a service contract asks for
(`backend/unit_conversion.py`). Built from QUDT v3.5.2,
`src/main/rdf/vocab/unit/VOCAB_QUDT-UNITS-ALL.ttl`:

    python scripts/build_qudt_conversions.py VOCAB_QUDT-UNITS-ALL.ttl v3.5.2

Same source and licence as above (CC BY 4.0, QUDT Project).
