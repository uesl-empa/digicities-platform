# Ontology workspace

This is the directory the Streamlit **Ontology Manager** reads and writes when it runs in local mode (no NextCloud). The backend resolves it via the `ONTOLOGY_DIR` environment variable, which the Docker container sets to `/app/data/ontology` by default.

## Layout

```
data/ontology/
├── dici_onto_core.ttl       Read-only seed of the core ontology.
├── term-index.json          Generated term lookup (one card per core term), vendored.
├── term-index.md            Same index, greppable Markdown.
├── imports/
│   └── qudt_units.txt       QUDT unit list surfaced in attribute forms.
├── extensions/              User-created extension TTLs (editable).
├── exports/                 Merged core+extension exports, written by the UI.
├── temp/                    Working copies during an edit session.
└── mappings/
    ├── input/               Mapping-rule input TTLs.
    └── output/              Generated mapping output TTLs.
```

`dici_onto_core.ttl` and `imports/qudt_units.txt` are the same files that seed the triplestore container (Fuseki by default, or GraphDB with the opt-in overlay), from `services/graphdb/ontology/`. Treat them as read-only — for schema changes, add an extension under `extensions/` instead of editing the core.

`term-index.{json,md}` are vendored from [digicities-ontology](https://github.com/uesl-empa/digicities-ontology) `docs/`, where they are generated from the core TTL by `tools/generate_term_index.py`. They give agents and humans an offline lookup of every core term's annotations (`rdfs:comment`, `skos:definition`, `skos:altLabel` synonyms, `skos:example`, `skos:scopeNote`) plus its parent chain — see the ontology repo's [`docs/AGENT_MAPPING_GUIDE.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/AGENT_MAPPING_GUIDE.md) for how to use them. Refresh them together with `dici_onto_core.ttl` when bumping the vendored ontology version.
