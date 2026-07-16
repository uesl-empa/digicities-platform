# Architecture

Two layers, one rule:

```
+----------------------------------------------------+
|  apps/streamlit/                  ← UI shells       |
|    app.py                                           |
|    components/<module>.py        (thin Streamlit)   |
+----------------------------------------------------+
                       │ imports
                       ▼
+----------------------------------------------------+
|  backend/                         ← pure Python     |
|    graphdb/                                         |
|    ontology_manager/                                |
|    replica_builder/                                 |
|    assumptions/                                     |
|    data_products/                                   |
|    api_submission/                                  |
+----------------------------------------------------+
                       │ talks to
                       ▼
+----------------------------------------------------+
|  Fuseki (RDF/SPARQL)   ·  NextCloud (WebDAV)        |
|  Keycloak (optional)   ·  external services (HTTP/Redis) |
+----------------------------------------------------+
```

**The rule**: `backend/` never imports `streamlit`. Verified — there are no `import streamlit` references inside `backend/`. This means every backend module is callable from a notebook, a CLI, a FastAPI handler, or a test, without dragging a UI runtime in.

## Are the functions hardcoded into Streamlit?

No, not for the core domain logic. The pattern is:

- `backend/<module>/` — every function that mutates GraphDB, parses TTL, generates RDF, calls an external API, or implements a business rule.
- `apps/streamlit/components/<module>.py` (or a sibling subfolder) — a Streamlit shell that builds the form, calls the backend, and renders the result.

The tutorial notebooks under `tutorial/` exercise this directly — they import from `backend.*` and never touch Streamlit. That's the proof the layering holds for the documented happy paths.

## Per-module status

| Backend subpackage | UI component | Coupling |
|---|---|---|
| `backend/graphdb/` | `components/graphdb.py` | **Thin shell.** UI injects a Keycloak token refresher + error toasts; all SPARQL execution stays in backend. |
| `backend/ontology_manager/` | `components/ontology_manager/` | **Thin shell.** UI delegates every CRUD call to `OntologyFunctions`. |
| `backend/replica_builder/` | `components/replica_builder/` | **Mostly thin.** TTL generation (`process_excel_to_ttl`, `generate_attribute_ttl`) lives in backend. Some attribute-form rendering helpers in the UI build small TTL fragments inline. |
| `backend/scenario_builder/` | `components/scenario_builder/` | **Mostly thin.** Headless scenario TTL generation (`build_scenario_ttl`) lives in backend; the interactive scenario-editing forms are in the UI shell. |
| `backend/assumptions/` | `components/assumptions/` | **Medium.** Predefined assumption construction lives in backend; the per-row "modify this assumption" form inlines some validation. |
| `backend/data_products/` | `components/data_products/` | **Medium.** TTL parsing is in backend; NextCloud I/O and path resolution are in the UI shell. |
| `backend/api_submission/` | `components/api_submission_module/` | **Medium.** Generic HTTP/Redis transports + the TTL→payload converter are in backend (`transports.py`, `ttl_converter.py`); the UI inlines service registration and result rendering. |

## UI-only modules (no backend twin, by design)

These don't have a `backend/` counterpart because they're *about* the UI shell, not domain logic:

- `components/auth.py` — Keycloak login flow / `AUTH_DISABLED` shortcut.
- `components/workspace_selector.py` — workspace picker for the sidebar.
- `components/system_status.py` — read-only diagnostic sidebar (GraphDB, NextCloud, ontology, services).
- `components/nextcloud_client.py` / `nextcloud_global_client.py` / `nextcloud_module.py` — WebDAV client + browse panel.

## Known leaks

Places where logic *should* migrate into `backend/` but currently sits in a Streamlit file. Contributors picking up these areas should consider extracting first:

1. **`components/query_manager.py`** — embeds SPARQL execution, Nextcloud query-file I/O, and session caching directly. No `backend/query_manager/` module exists yet. ~300 LOC.
2. **`components/component_explorer.py`** — four+ SPARQL queries for component-type discovery and attribute lookup live inline. No backend twin. ~400 LOC.
3. **`components/service_requirements_builder.py`** — ontology-parsing SPARQL queries embedded; rdflib used directly from the UI.

These are pragmatic tech-debt items, not architectural commitments — they were faster to ship as Streamlit-first and will move to `backend/` when they grow a second consumer (notebook, CLI, or API).

## Building a non-Streamlit frontend

You can replace `apps/streamlit/` wholesale today for the modules with a clear backend twin (graphdb, ontology_manager, replica_builder, assumptions, data_products, api_submission). For the leaky modules above, the SPARQL strings and orchestration would need to be lifted out of the Streamlit file into a backend module first — straightforward but not free.

The `tutorial/` notebooks are the reference for what "using the backend without the UI" looks like.

## Runtime layout

| Component | Where it runs | Default port |
|---|---|---|
| Fuseki (default triplestore) | Docker (`docker-compose.yml`) | 3030 |
| GraphDB (optional overlay) | Docker (`docker-compose.graphdb.yml`) | 7201 |
| Streamlit | Docker (`docker-compose.yml`) | 8501 |
| NextCloud (optional) | Docker (`docker-compose.nextcloud.yml` overlay) | 8080 |
| Keycloak (optional) | external; off by default via `AUTH_DISABLED=true` | — |

Storage backend for workspaces is selected by `STORAGE_BACKEND=local` (default, files under `data/`) or `=nextcloud` (WebDAV via `NEXTCLOUD_*` env vars). The same backend code paths are used in both modes.
