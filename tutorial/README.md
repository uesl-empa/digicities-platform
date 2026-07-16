# Digicities Tutorial

Hands-on tutorials for the Digicities platform — a knowledge-graph toolkit for modelling urban energy systems.

The tutorials walk through the same workflow the Streamlit UI automates, but in Jupyter notebooks against the Python backend. That way you can see exactly what data the platform is building up and how to extend it.

## What you'll need

- Docker Desktop (for the Fuseki + Streamlit stack)
- Python 3.9+ with Jupyter
- This repository cloned locally

No credentials or cloud accounts required — everything runs locally with `AUTH_DISABLED=true`.

## Quick start

One command from the repo root brings up the stack, loads the sample data, and opens the first notebook in Jupyter:

```bash
python tutorial/start_tutorial.py
```

That runs `docker compose up -d`, waits for Fuseki at `http://localhost:3030`, creates the `workspace_demo` dataset, loads the core ontology plus `sample_data/alpine_village.ttl` into it, and launches Jupyter Lab on `01_ontology_basics.ipynb`.

**If the NextCloud overlay is enabled** (see [`08_nextcloud.md`](08_nextcloud.md)), the launcher also seeds the workspace with an ontology extension and three data products (demand CSV, PV generation CSV, GeoJSON map) so the Streamlit UI has content in every module — not just empty states. Silent no-op when NextCloud isn't running.

See [`00_setup.md`](00_setup.md) if you'd rather do the steps manually or hit a snag.

Useful flags:

- `--no-docker` — skip the compose step (already running Fuseki yourself).
- `--no-load` — skip uploading the sample data.
- `--notebook 03_scenario_builder.ipynb` — open a different notebook.

## Tutorial order

| # | Topic | Notebook |
|---|---|---|
| 0 | Setup | [`00_setup.md`](00_setup.md) |
| 1 | Ontology basics — exploring the schema | [`01_ontology_basics.ipynb`](01_ontology_basics.ipynb) |
| 2 | Replica builder — building a digital twin in code | [`02_replica_builder.ipynb`](02_replica_builder.ipynb) |
| 3 | Scenario builder — fetching a baseline | [`03_scenario_builder.ipynb`](03_scenario_builder.ipynb) |
| 4 | Assumptions — modifying scenarios | [`04_assumptions.ipynb`](04_assumptions.ipynb) |
| 5 | Data products — parsing and inspecting TTL | [`05_data_products.ipynb`](05_data_products.ipynb) |
| 6 | API submission — pushing to external solvers | [`06_api_submission.ipynb`](06_api_submission.ipynb) |
| 7 | Streamlit UI walkthrough — same workflow, in the browser | [`07_streamlit_ui.md`](07_streamlit_ui.md) |
| 8 | Local NextCloud — browsable blob storage (optional)      | [`08_nextcloud.md`](08_nextcloud.md) |
| 9 | Excel ingestion — populating the twin from a spreadsheet | [`09_excel_import.ipynb`](09_excel_import.ipynb) |

## The running example: Alpine Village

All tutorials share the same fictional Swiss district, defined in [`sample_data/alpine_village.ttl`](sample_data/alpine_village.ttl):

- **Building A** — single-family house with a rooftop PV array and a home battery
- **Building B** — apartment block heated by an air-source heat pump
- **Building C** — single-family house, passive consumer
- **Grid** — regional electricity connection
- **District heat loop** — serves Building B

This is deliberately tiny (~132 triples) so you can read the raw TTL end to end. Real projects have thousands of triples per workspace.

## Getting help

If you hit a problem: open an issue on the repo. The notebooks print the exact SPARQL queries they send, so including that output in a bug report is usually enough context.
