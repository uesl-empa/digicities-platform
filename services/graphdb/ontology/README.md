# Vendored ontology

Snapshot of the [Digicities ontology](https://github.com/uesl-empa/digicities-ontology) used to seed the triplestore container (Apache Jena Fuseki by default, or GraphDB with the opt-in overlay) on first boot. The pinned version is recorded in [`VERSION`](VERSION).

## Files

| File | Source | License |
|---|---|---|
| `dici_onto_core.ttl` | [digicities-ontology](https://github.com/uesl-empa/digicities-ontology) `core/dici_onto_core.ttl` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `qudt_units.txt` | [QUDT](https://www.qudt.org/) (Topquadrant Inc.) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

The same files are mirrored under `data/ontology/` for local-mode tooling (the Ontology Manager UI). Keep both copies in sync when bumping the version — see the platform README's *Ontology* section for the refresh recipe.

## Why a vendored copy?

A fresh `docker compose up` should bootstrap the triplestore without network access to GitHub. Pinning a version (rather than always pulling latest) also means platform releases are reproducible — a given platform release always boots with its pinned ontology version (recorded in `VERSION`).
