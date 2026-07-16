# Getting started with Digicities

This guide takes you from a fresh clone to running two complete, working pipelines,
and explains the ideas as you go. It's written for energy researchers and planners,
not RDF experts - you don't need prior knowledge of ontologies or SPARQL.

> The two pipelines below - **energy simulation** and the **flexibility optimiser** -
> are the supported, end-to-end workflows. They are the model for how everything on
> the platform works: describe buildings as data, build a what-if scenario, hand it
> to an external model, get results back. Some other modules are still under
> development (flagged 🚧 in the app); this guide sticks to the working paths.

---

## 1. What Digicities is

Digicities is a workbench for building **digital twins of the built environment** as a
knowledge graph, and running what-if analyses on them. You describe buildings,
locations, generators and flows once - as structured, self-describing data - then hand
a scenario off to any external model (an energy simulator, a flexibility optimiser,
your own tool) and get results back. The data lives once; the models plug in.

Under the hood it's a Streamlit app over an RDF triplestore (Apache Jena Fuseki by
default), but you interact with it through modules in the UI.

## 2. Quickstart (5 minutes)

Requirements: Docker Desktop.

**1. Clone the repo and create your config:**

```bash
git clone <this-repo> digicities-platform
cd digicities-platform
cp .env.example .env          # your local config — ships with sensible defaults, no secrets
```

`.env` is git-ignored; `.env.example` is the template. The defaults (local storage,
Fuseki, login disabled) work as-is, so you can leave `.env` untouched unless you want
one of the options below.

**2. (Optional) Load your own local workspaces — do this *before* starting.**
Out of the box you get the two bundled demos (below). To *also* load your own
workspaces — any folder that follows the workspace template layout — point
`USECASES_HOST_PATH` at the directory that **contains** them. Set it in `.env`
(absolute path; forward slashes on Windows):

```ini
# .env
USECASES_HOST_PATH=/path/to/my-workspaces
```

Every template-structured subfolder — one with a `workspace_meta/` folder plus an
`ontology/extensions/`, `scenarios/`, or `ingestion/output/` dir — is auto-discovered
and appears in the landing window next to the demos. The folder is mounted
**read-write** at `/app/data/usecases`, so edits you make in the app write straight
back to those folders on disk. Because the app runs in Docker it can only see paths
mounted this way, which is why this is set before `docker compose up`. Skip this step
to just use the bundled demos.

**3. Start the stack:**

```bash
docker compose up -d --build
```

Open **http://localhost:8501**. Login is disabled for local use, so you land straight
in the app. Two demo workspaces are bundled and appear automatically (they show
regardless of `USECASES_HOST_PATH`):

- **Energy Simulation (demo)** - self-contained, no external services needed.
- **Motel energy** - a second sample workspace.

Nothing else to configure.

### Storage: local (default) or NextCloud (optional)

By default the platform stores workspace files on the **local filesystem** — no
extra services, nothing to configure. Every module reads and writes through one
storage abstraction, so **file operations are identical** whether the backend is
local disk or NextCloud; NextCloud simply puts the same files on a WebDAV server.

To switch to the bundled local **NextCloud** (a browsable file server at
`http://localhost:8080`, admin/admin), edit `.env`:

1. Uncomment the `COMPOSE_FILE` and `COMPOSE_PATH_SEPARATOR` lines in the NextCloud
   section.
2. Set `STORAGE_BACKEND=nextcloud`.
3. Run `docker compose up -d`.

To go back to local, re-comment those two lines and set `STORAGE_BACKEND=local`.
The bundled demo workspaces stay local either way. (To use your own remote
NextCloud instead of the bundled container, see the `.env` NextCloud section.)

## 3. The core ideas (read once)

| Term | What it means here |
|---|---|
| **Ontology** | The shared vocabulary - the classes (Building, Location, Scenario) and attributes (GroundFloorArea, HeatingSupply, ...) everything is described with. Read-only; you build on it. |
| **Knowledge graph** | The per-workspace triplestore. It holds your **digital replica** (building instances + attribute values) and your **scenarios**. |
| **Digital replica** | The buildings/locations of your workspace, as instances in the graph. You see them in the **Digital Replica Explorer**. |
| **Scenario** | A selection of replica components plus what-if overrides (e.g. "retrofit this building to a heat pump"). Thin - it references the replica, it doesn't copy it. |
| **Service** | An external model you submit a scenario to (an energy simulator, an optimiser). A **service template** (YAML) maps ontology terms to the payload the service wants. |

The key move, everywhere on the platform: a **service template** names the ontology
terms a model needs; the **knowledge graph** holds the values; the platform **converts**
a scenario into plain JSON the model understands and submits it. The model never sees RDF.

## 4. The modules

Guided workflow (the two pipelines use these):

- **Digital Replica Explorer** - browse the buildings/instances in the workspace graph.
- **Ontology Manager** - view/extend the vocabulary (no triplestore needed).
- **Replica Builder** - build building instances from a spreadsheet or by hand.
- **Scenario Builder** - assemble a scenario (pick components, add overrides).
- **API Data Submission** - register a service, convert a scenario to its payload, submit, and view results.

Archived / under development (not covered here): Query Manager, Data Viewer and Uploader,
Data Products, Assumptions Module. They're **hidden by default**; tick **"Show archived
modules"** in the sidebar to reveal them (they're flagged 📦 when shown).

---

## 5. Pipeline 1 - Energy simulation (fully offline)

This runs end to end with only the bundled stack - no external accounts, no internet.
It estimates each building's annual energy demand.

1. **Open the workspace.** In the sidebar, select **Energy Simulation (demo)**.
2. **See the digital replica.** Open **Digital Replica Explorer** - you'll see the sample
   buildings (an MFH, an SFH, an office, ...) with their attributes. This data lives in
   the workspace's knowledge graph; it's what the scenario draws on.
3. **Connect the service.** Open **API Data Submission → 🔧 API Configuration**. The
   bundled **`demo_energy_simulator`** service auto-registers (it's declared in the
   workspace's service template). Nothing to type.
4. **Convert a scenario.** Go to **📁 Upload & Convert**, pick service
   `demo_energy_simulator`, pick a scenario (e.g. *Energy Sim - Baseline (MFH)* or the
   *Heat pump retrofit* what-if), and click **Convert**. This is the semantic step: the
   platform walks the scenario in the graph and produces the JSON payload.
5. **Submit.** Go to **🚀 API Submission** and **Submit**. You get a **results dashboard
   link** (`http://localhost:5001/...`) - open it to see the annual demand per building.
   Results are also saved to the workspace.

That's the whole shape of the platform: replica → scenario → convert → submit → results.

## 6. Pipeline 2 - Flexibility optimiser (with a dashboard + live weather)

This shows the same flow against a richer external service: a battery/flexibility
optimiser that returns an interactive **dashboard**, a downloadable results JSON, and can
run on **live weather**. The optimiser is a separate app (the flexibility-prototype),
optionally fed live weather from an external weather-feed stack.

**Start the flexibility app** (in a sibling checkout):

```bash
git clone <flexibility-prototype-repo> flexibility-prototype
cd flexibility-prototype
docker compose up -d --build      # serves on http://localhost:8001
```

It runs on an open-source solver (SCIP) - no commercial licence needed.

**In Digicities:**

1. **Open a flexibility workspace** (one mounted via `USECASES_HOST_PATH`, or copy a
   flexibility `services/` + `scenarios/` set into any workspace).
2. **API Configuration** - the **`FlexibilityOptimizer`** service auto-registers, pointing
   at the flexibility app (`http://host.docker.internal:8001/api/digicities/run`). To use
   a pure Redis-stream optimiser instead, set `FLEX_SERVICE_URL=http://host.docker.internal:8090/run`.
3. **Convert** a flexibility scenario, then **Submit**.
4. The result view shows links for whatever the service returned - **Open dashboard**,
   **Download results (JSON)**, **Results (JSON API)**. Open the dashboard to explore the
   optimised battery/PV/EV behaviour.

**Live weather (optional).** A scenario can point a location at a live weather feed
(`weather_stream`, e.g. `forecasts.met-no.VIENNA`). If that Redis stream (published by the
weather-feed stack's data-crawler) has data, the optimiser uses live temperatures; otherwise it
falls back to static archetype weather. The response tells you which via `weather_source`
(`live`/`static`) and a `weather_detail` note. To try it without the crawler, seed the
stream once:

```bash
docker exec -i <weather-redis> redis-cli XADD forecasts.met-no.VIENNA "*" \
  air_temperature_2m "[1,0,-1,-1,0,2,4,6,8,10,11,12,12,11,10,8,6,4,3,2,1,1,0,0]"
```

## 7. How the repositories fit together

| Repo | Role |
|---|---|
| **digicities-platform** (this repo) | The UI + backend: build replicas/scenarios, convert, submit. The hub. |
| **digicities-ontology** | The shared vocabulary (classes/attributes). Vendored here; edited upstream. |
| **digicities-usecase-template** | Scaffold for creating your own workspace. |
| **flexibility-prototype** | The flexibility optimiser + results dashboard (Pipeline 2). Digicities reaches it at `:8001`. |

A service is just "an HTTP (or Redis) endpoint + a template describing its payload". Both
pipelines above are the same pattern with a different service behind them.

## 8. Troubleshooting

- **Empty workspace list** - the bundled `energy-simulation` demo always ships in the image
  and should appear; if not, check `docker compose logs streamlit`.
- **Fuseki** runs on `:3030` (the default triplestore). GraphDB is an optional overlay; the
  older notebook tutorial (`tutorial/`) still assumes GraphDB and is being updated - use this
  guide and the UI pipelines instead.
- **Flexibility submit fails** - the flexibility-prototype must be running on `:8001`
  (`docker compose up` in that repo). Digicities reaches it via `host.docker.internal`.
- **`weather_source: static`** despite a live scenario - the weather stream is empty; run the
  RDP crawler or seed the stream (§6).
