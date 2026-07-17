# AGENTS.md — orientation for agents working on Digicities

Digicities is a knowledge-graph platform for urban energy/system modelling. A
user describes a system as **instances of an RDF/OWL ontology** (a *digital
replica*), derives **scenarios**, and **submits** them to external models/services
(simulators, optimizers, forecasters) that return results.

This file orients an automated agent. Humans should start at
[`README.md`](README.md) and [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md).

## The most common agent task: onboard a new usecase

Given an existing model plus a pile of its input data, make it work with
Digicities. The end-to-end recipe is
**[`docs/ONBOARDING_A_USECASE.md`](docs/ONBOARDING_A_USECASE.md)** — read it first
for this kind of task. It builds on
[`docs/INTEGRATING_A_SERVICE.md`](docs/INTEGRATING_A_SERVICE.md) (the 7-step
service-wiring recipe).

The target end-state for a usecase is a **workspace** (a folder following
[`docs/WORKSPACE_LAYOUT.md`](docs/WORKSPACE_LAYOUT.md)) containing an ontology
extension, a replica, scenarios, and a service template.

## Repo map

| Path | What's there |
|---|---|
| `apps/streamlit/app.py` | The Streamlit UI entry point |
| `apps/streamlit/components/` | UI modules (Replica Builder, Scenario Builder, Service Requirements Builder, API Submission, …) — thin shells over `backend/` |
| `backend/` | Pure-Python core (no Streamlit): `graphdb/` (triplestore client + SPARQL), `triplestore/` (Fuseki/GraphDB backends), `replica_builder/`, `assumptions/`, `api_submission/` (incl. `ttl_converter.py`, the scenario→payload converter), `workspace/` (provisioning, registry) |
| `data/ontology/` | The core ontology (`dici_onto_core.ttl`) used in local mode |
| `data/global_services/` | Bundled service templates (`demo_energy_simulator.yaml`, `flexibility_optimizer.yaml`) — the canonical shape for a `services/*.yaml` |
| `demo_workspaces/` | Self-contained example workspace (`energy-simulation`) — copy its structure |
| `tutorial/` | Jupyter notebooks (01–06 + 09) walking the API against the backend; `09_excel_import.ipynb` is the spreadsheet→replica path |
| `docs/` | All guides (see below) |
| `docker-compose.yml` | The default stack: Apache Jena Fuseki (`:3030`) + Streamlit (`:8501`) |

## Key docs

| Doc | Read it when |
|---|---|
| `docs/GETTING_STARTED.md` | First contact — what it is, the two working pipelines |
| `docs/ONBOARDING_A_USECASE.md` | Bringing a new model + data onto the platform |
| `docs/INTEGRATING_A_SERVICE.md` | Wiring the service itself (ontology → template → transport → submit) |
| `docs/WORKSPACE_LAYOUT.md` | The exact workspace folder contract |
| `docs/SEMANTIC_LAYER.md`, `docs/sparql_query_reference.md` | The ontology model + how to query it |
| `docs/INFERENCE.md` | How provisioning materialises the RDFS closure into named graphs |
| `docs/ARCHITECTURE.md`, `docs/ROADMAP.md` | System shape + what's intentionally not built yet |

## Conventions that bite (learn these early)

- **Query the graph semantically.** Resolve types via `rdfs:subClassOf*` /
  `rdfs:subPropertyOf*` over the ontology — never string-match on a class-name
  suffix like `…Attribute`. Extension classes won't match string patterns.
- A component type must be `rdfs:subClassOf* dici_onto:Component` or it won't show
  in the Explorer / Scenario Builder.
- The converter reads attribute values from **`qudt:value`** only.
- Scenario links are `dici_onto:ComponentLink` nodes with `dici_onto:hasInputEntity`
  and `dici_onto:linksInputyEntityTo` (note the odd spelling — match it exactly).
- Default triplestore is **Fuseki** on `:3030` (`TRIPLESTORE_BACKEND=fuseki`);
  Fuseki needs HTTP Basic admin auth for **writes** (reads are open). GraphDB is
  an optional overlay on `:7201`.
- From the running app (in a container), external endpoints are
  `host.docker.internal:<port>`, not `localhost`.
- After editing an ontology extension, re-open the workspace so its dataset
  re-provisions.

## Setup — present these options to the user BEFORE `docker compose up`

The stack is configured entirely in `.env` before it starts: the app runs in
Docker and only sees what's mounted/set at launch, so these are pre-Docker
decisions. Every one has a sensible default — a user who just wants to try it can
accept all three and skip straight to "Running it" below. First create the config
from the template — **`cp .env.example .env`** (`.env` is git-ignored; only the
example ships) — then walk the user through these and edit `.env` accordingly. The
agent can make these edits for the user or hand them the exact lines to paste. This
list also answers "what am I choosing here?".

1. **Do you have an existing workspace to load?**
   - **Yes — a folder, or a folder *of* folders, of workspaces** (e.g. your own
     set) that follow [`docs/WORKSPACE_LAYOUT.md`](docs/WORKSPACE_LAYOUT.md): set
     `USECASES_HOST_PATH` in `.env` to the directory that *contains* them. Every
     template-structured subfolder (has `workspace_meta/` + an `ontology/extensions/`,
     `scenarios/`, or `ingestion/output/` dir) is auto-discovered and appears on the
     landing page. Mounted **read-write** at `/app/data/usecases`, so in-app edits
     write back to disk.
   - **No — start fresh:** skip it. Create one from the landing page's "Create a new
     workspace" form, or onboard a model + its data with
     [`docs/ONBOARDING_A_USECASE.md`](docs/ONBOARDING_A_USECASE.md).
   - Either way the two bundled demos always appear (independent of the mount).

2. **Where should workspace files live? — storage backend.**
   - **Local filesystem** (default): files on disk under the mounted dir; no extra
     services. `STORAGE_BACKEND=local`.
   - **NextCloud** (opt-in): files on a bundled WebDAV server, browsable at `:8080`.
     Uncomment the NextCloud `COMPOSE_FILE` + `COMPOSE_PATH_SEPARATOR` lines in `.env`
     and set `STORAGE_BACKEND=nextcloud`. Note: NextCloud is **AGPL-3.0**; the default
     local stack ships no AGPL component. File operations are identical either way —
     one fsspec-backed abstraction (`ctx.storage`), so nothing else changes.

3. **Which triplestore? — the knowledge-graph store.**
   - **Apache Jena Fuseki** (default, Apache-2.0, `:3030`): fine for everything.
   - **Ontotext GraphDB Free** (opt-in, **proprietary** EULA, `:7201`): richer
     Workbench UI + inference. Add `docker-compose.graphdb.yml` to `COMPOSE_FILE` and
     set `TRIPLESTORE_BACKEND=graphdb`.

Defaults in `.env.example` (which you copy to `.env`): **local storage, Fuseki,
`AUTH_DISABLED=true`, no secrets.**

## Running it

```bash
cp .env.example .env             # create your local config (edit per the setup options above)
docker compose up -d --build     # Fuseki :3030 + Streamlit :8501 (+ demo simulator)
```

Then open http://localhost:8501. Notebook path: `python tutorial/start_tutorial.py`.
Full step-by-step for humans: [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md).
