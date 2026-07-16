# Imports

External vocabularies bundled here for offline lookup by the platform's UI.

## `qudt_units.txt`

A flat list of QUDT unit short codes (e.g. `KiloW-HR`, `M2`, `CHF`) used to populate the unit dropdowns in the Replica Builder's attribute forms.

**Source:** [QUDT — Quantities, Units, Dimensions, and Data Types in OWL/XML](https://www.qudt.org/) (QUDT Project, maintained by Topquadrant Inc.)

**License:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)

QUDT is freely redistributable with attribution. If you derive a new units file from QUDT, retain this README and the attribution above.

## Refreshing

The full QUDT distribution is at <https://github.com/qudt/qudt-public-repo>. To regenerate `qudt_units.txt` from a newer QUDT release, dump every `qudt:Unit` IRI and strip the namespace prefix — the file is one short-code per line.
