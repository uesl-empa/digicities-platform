# 07 — Streamlit UI walkthrough

Notebooks 01–06 exercised the Python backend directly. Same platform, same data model — this tutorial drives the UI at [http://localhost:8501](http://localhost:8501) against the **Alpine Village** sample.

If you've run the notebook launcher (`python tutorial/start_tutorial.py`), the sample data is already in the triplestore (Apache Jena Fuseki by default) under the graph `<https://digicities.info/tutorial/alpine_village>` and the UI is pointed at the `workspace_demo` dataset. Nothing else to set up.

## Prerequisites

- Stack is up: `docker compose ps` shows `digicities-fuseki` and `digicities-streamlit` as `running`.
- Alpine Village loaded. If you skipped the notebook launcher, load it manually:

  ```bash
  python tutorial/start_tutorial.py --no-docker --notebook 01_ontology_basics.ipynb
  ```

  or run the upload cell in `01_ontology_basics.ipynb`.

- `.env` has `AUTH_DISABLED=true` and `LOCAL_WORKSPACE=workspace_demo` (the defaults).

Open [http://localhost:8501](http://localhost:8501). No login screen — you land directly on the platform with `workspace_demo` pre-selected in the sidebar.

## The sidebar layout

The left sidebar has two selectors:

| Selector | What it picks |
|---|---|
| **Workspace** | Which triplestore dataset the modules read from. Locally, the only option is `workspace_demo`. |
| **Select Module** | Which feature you're using. The main ones for local work are listed below. |

Modules that need NextCloud (Data Viewer and Uploader) are visible but will complain without credentials — you can ignore them. API Data Submission works with the bundled demo services (no credentials needed).

## Module tour

This tour maps each UI module to the notebook that shows the equivalent backend call. Clicking around and checking the notebook side-by-side is the fastest way to see what the UI is actually doing.

### 1. Digital Replica Explorer — *maps to `01_ontology_basics.ipynb`*

**What it is.** A table+filter view over every component in the workspace. The same SPARQL the notebook runs by hand.

**Try it.**

1. Select **Digital Replica Explorer** from the module list.
2. Pick the named graph `https://digicities.info/tutorial/alpine_village` from the graph selector (if the UI surfaces one). If not, the default graph shows everything in the repo.
3. You should see the three Alpine Village buildings, the grid connection, and the district heat loop.
4. Expand a building row — attributes like *Floor area*, *Peak electrical demand* appear with their QUDT units.

**Gotcha.** If the table is empty, the sample data hasn't been loaded. Run cell 1.2 of `01_ontology_basics.ipynb` (the `upload_ttl(...)` call with `replace_existing=True`).

### 2. Ontology Manager — *no notebook counterpart, this is schema-editing UI*

**What it is.** CRUD over the core ontology plus any local **extensions**. Classes, attributes, object properties, mapping rules.

**Try it (local-fs mode).**

1. Select **Ontology Manager**.
2. Click through **Classes → EnergyGenerator** and look at its subclasses (`PhotovoltaicSystem`, `WindTurbine`, …).
3. Open **Attributes** and find `ratedPower` — this is the attribute that PVs and heat pumps in the village hang values off.

**Try it (with the NextCloud overlay).** `start_tutorial.py` uploads `alpine_village_extension.ttl` to `workspace_demo/ontology/extensions/`. In the Ontology Manager:

1. From the extensions dropdown, pick **alpine_village_extension.ttl** and load it.
2. You'll see new classes appear: `AlpineDistrictHeating`, `RooftopPhotovoltaicSystem`, `SeasonalHeatDemandNote`, plus two physical attributes (`PanelTilt`, `PanelAzimuth`) and an object property `servesDistrict`.
3. All of these layer on top of `dici_onto_core` — the extension is the pattern you'll follow for your own project vocabulary.

For the tutorial treat the core ontology as read-only — poking at definitions is fine, but don't rename `dici_onto:EnergyConsumer`. Edits to the *extension* are safe.

### 3. Replica Builder — *maps to `02_replica_builder.ipynb`*

**What it is.** The interactive way to build up a replica — add components, give them attributes, wire them together with links. Under the hood it writes to two fixed named graphs:

| Graph | Holds |
|---|---|
| `<http://classes_and_attributes>` | Components and their attributes |
| `<http://system_description>`     | Links between components (flows, containment, etc.) |

These URIs are **hard-coded** in `replica_graph_loader.py` — the Builder always reads/writes those two graphs and no others. The tutorial launcher (`start_tutorial.py`) mirrors Alpine Village into both so the "Load Graphs" button finds something.

**Try it.**

1. Select **Replica Builder**.
2. Expand **Existing Graphs in Triplestore** and click **📥 Load Graphs**. You should see `classes_and_attributes: 132 triples, N instances found` and `system_description: 132 triples`.
3. Click **📋 Populate Instances**. The buildings, PV, battery, heat pump and grid appear in the instance list. Expand one to see its attributes.
4. Add a new component: e.g. *GasBoiler* named `Boiler-C`, attributes `ratedPower = 18 kW`, linked to `BuildingC`. The UI generates the TTL and pushes it into `<http://classes_and_attributes>` / `<http://system_description>`.
5. Switch back to **Digital Replica Explorer** (which queries across all graphs) and confirm the boiler appears.

**A subtlety — flow links.** The Replica Builder models links as direct `(source-component, predicate, target-component)` triples. Alpine Village uses intermediate `Flow` resources (`BuildingA dici_onto:hasInputFlow Flow_Grid_to_A`, then `Flow_Grid_to_A dici_onto:carriesEnergyCarrier av:Electricity`). Because the Flow nodes aren't themselves components (they have no `hasAttribute`), the Builder's link parser filters them out. So the **instances** populate; the **flows-as-links** do not. Notebook 02 has the same data layout and explains the trade-off.

The notebook equivalent (`02_replica_builder.ipynb`) builds the same TTL in pure Python using `backend.replica_builder.utils`. If you want to see the exact TTL the UI generated, run the "dump graph as turtle" cell in notebook 02 against `<http://classes_and_attributes>`.

### 4. Query Manager — *adjacent to `01_ontology_basics.ipynb`*

**What it is.** A SPARQL console wired to the current workspace. Useful for anything the Explorer can't slice.

**Try it.** Paste in the "count by type" query from `01_ontology_basics.ipynb`:

```sparql
PREFIX dici_onto: <https://digicities.info/ontology#>
SELECT ?type (COUNT(?c) AS ?n) WHERE {
  GRAPH <https://digicities.info/tutorial/alpine_village> {
    ?c a ?type .
    FILTER(STRSTARTS(STR(?type), 'https://digicities.info/ontology#'))
  }
} GROUP BY ?type ORDER BY DESC(?n)
```

You should see the same component counts the notebook produced.

### 5. Scenario Builder — *maps to `03_scenario_builder.ipynb`*

**What it is.** Builds a baseline snapshot of the workspace — a TTL export of exactly the state you want to run scenarios against.

**Try it.**

1. Select **Scenario Builder**.
2. Pick **Alpine Village** as the source graph.
3. Click **Build baseline**. The module writes a TTL file named something like `baseline_alpine_village_<timestamp>.ttl` into your local `data/` workspace.
4. Notebook 03 does the same thing by calling `backend.graphdb.export_graph(...)` and writing the file itself.

### 6. Assumptions Module — *maps to `04_assumptions.ipynb`*

> Archived module — tick **"Show archived modules"** in the sidebar to reveal it.

**What it is.** Generates *what-if* variants of an existing scenario: load a baseline,
change a few attributes, and it writes a new scenario. Three ways to change things:

- **Single**: apply one predefined rule (e.g. *"increase wind turbine power by 50%"*).
- **Series**: sweep a parameter over timesteps (e.g. a cost learning curve).
- **Manual**: edit individual attribute values on the components you pick. Categorical
  attributes are constrained to the ontology's valid values (named individuals /
  subclasses), the same as the Replica Builder.

**What it writes.** A **thin** scenario — it references the baseline's replica components
and carries only `dici_onto:supersedesAttribute` overrides for what you changed, the
same shape as a Scenario Builder / hand-authored scenario (see
`demo_workspaces/energy-simulation/scenarios/energy_sim_retrofit.ttl`). Unchanged
attributes inherit from the replica when the scenario is materialised, so even a
one-attribute edit produces a complete, submittable scenario.

**Try it.**

1. Load a baseline (e.g. *Energy Sim - Baseline (MFH)*).
2. **Manual** → pick a component → set *HeatingSupply* to *Air / heat pump* → apply → generate.
3. **View Scenarios → View TTL**: one override, everything else inherited.
4. **Export → Upload to Workspace** → it appears in the workspace `scenarios/` list,
   ready for the API Submission tab.

The engines are `backend.assumptions.assumption_engine` (single + series),
`backend.assumptions.manual_modification_engine` (manual), and
`backend.assumptions.thin_scenario_ttl` (the TTL writer) — the UI is a thin wrapper.

### 7. Data Products — *maps to `05_data_products.ipynb`*

**What it is.** Parses data-product manifest TTLs (e.g. hourly electricity demand profiles) and renders charts / maps / tables depending on the product type.

**Try it (with the NextCloud overlay).** `start_tutorial.py` seeds three products under `workspace_demo/private_data_products/`:

| Product | What it is | Renders as |
|---|---|---|
| `building_a_electricity_demand` | 168 h of hourly demand for the Building A SFH, with a plausible weekday/weekend shape | line chart |
| `pv_a_generation` | 168 h of PV output with a bell-curve solar day and cloud-modulation noise | line chart — compare against demand |
| `alpine_village_map` | 7-point GeoJSON of every component (3 buildings, PV, battery, heat pump, grid connection) | Folium map over the Swiss Alps |

Select **Data Products**, pick one from the private list, and the UI routes to the matching renderer.

**Try it (without NextCloud).** Upload a small TTL manifest + resources folder. The same renderer routing applies.

Notebook 05 demonstrates the same parsing via `backend.data_products.TTLParser`. The CSVs under `tutorial/sample_data/nextcloud/data_products/*/resources/` are what you'd load in a script.

### 8. API Data Submission — *maps to `06_api_submission.ipynb`*

Register a service, convert a scenario to its payload, and submit. The bundled
**demo energy simulator** works fully offline (no credentials) — the golden path in
`docs/GETTING_STARTED.md`. The **flexibility optimiser** is a separate app (see
GETTING_STARTED, Pipeline 2). A service auto-registers from its workspace template's
`connection:` block, so there's usually nothing to type.

### Sidebar: System Status — *read-only platform overview*

Not a module — lives in the left sidebar alongside **🔐 Session Management**, **📊 Workspace Info**, **🔧 Development Debug**, and **ℹ️ About**. Expand **📊 System Status** to see:

- **🧭 Platform** — environment mode, auth mode, active workspace, whether the UI is running inside Docker.
- **🔌 Triplestore** — backend URL, current dataset/repository, a connection probe, and every named graph with its triple count. Default is Fuseki (`http://localhost:3030/`); the optional GraphDB overlay exposes its Workbench at `http://localhost:7201/`.
- **💾 Storage** — backend (`local` or `nextcloud`), a summary of each `data/` subfolder (file count + total size), and a tabbed file browser with per-file download buttons. Since the UI runs in Docker it can't pop open your host OS file explorer; the download buttons are the equivalent for grabbing a file locally.
- **📚 Ontology** — resolved `ONTOLOGY_DIR`, core TTL status, and counts of extensions, exports, and mapping inputs.
- **🧩 Optional services** — whether NextCloud and Keycloak are configured. **Credential values are never displayed** — just a configured / not-configured badge.

**Try it.** Open the sidebar → expand **📊 System Status**. After the Alpine Village load, the "Named graphs in `workspace_demo`" table should list `<https://digicities.info/tutorial/alpine_village>`, `<http://classes_and_attributes>`, and `<http://system_description>` each with 132 triples. Under the **💾 Storage** section, click the `ontology/` tab to see the vendored core TTL, and the `namespaces/` or `queries/` tabs to inspect the other workspace folders.

This view is intentionally read-only. To change configuration edit `.env` and restart the container — see `.env.example` for the full set of variables.

## UI ↔ backend mapping at a glance

| UI module | Backend module | Tutorial notebook |
|---|---|---|
| Digital Replica Explorer | `backend.graphdb` | 01 |
| Ontology Manager | `backend.ontology_manager` | — |
| Replica Builder | `backend.replica_builder` | 02 |
| Query Manager | `backend.graphdb` | 01 |
| Scenario Builder | `backend.graphdb` + workspace storage | 03 |
| Assumptions Module | `backend.assumptions` | 04 |
| Data Products | `backend.data_products` | 05 |
| API Data Submission | `backend.api_submission` | 06 |
| System Status *(sidebar)* | reads env + filesystem + triplestore REST | — |

Anything the UI does, you can call from Python — the UI is a convenience layer, not a gatekeeper.

## Troubleshooting

**I see `ModuleNotFoundError: No module named 'backend'` in the browser.**
Your image was built before the `PYTHONPATH=/app` fix. Rebuild:

```bash
docker compose up -d --build streamlit
```

**The Explorer is empty.**
Alpine Village isn't loaded into `workspace_demo`. Re-run the upload cell in `01_ontology_basics.ipynb`, or:

```bash
python tutorial/start_tutorial.py --no-docker
```

(the `--no-docker` flag skips the compose step if the stack is already up).

**Ontology Manager crashes with `ModuleNotFoundError: No module named 'modular_dt_framework'`.**
The module is trying to resolve the ontology root from a private sibling package that isn't part of the open-source release. The fix is already applied — the backend now falls back to `data/ontology/` (container path `/app/data/ontology`) — but your stack may be using a stale image. Rebuild:

```bash
docker compose up -d --build streamlit
```

If you're running Streamlit from your host instead of the container, set `ONTOLOGY_DIR=./data/ontology` in your `.env` (or export it in the shell).

**"Workspace client not available" banner.**
The app couldn't talk to the triplestore. On the default stack, check `docker compose ps fuseki` is healthy and that `GRAPHDB_URL=http://fuseki:3030` (container-side). If you're on the optional GraphDB overlay, it's `http://graphdb:7200` container-side (`localhost:7201` is only for host-side notebooks).

**Port 8501 already in use.**
Something else is running a Streamlit app. Either stop it, or edit `docker-compose.yml` to map a different host port (e.g. `"8502:8501"`).

## Where to next

- Try the same workflow on your own data: create a new TTL in `data/` and upload it through Replica Builder instead of the Alpine Village sample.
- Read `apps/streamlit/components/` — each module is a single Python file that calls into `backend/`. The UI is deliberately thin; if you want to script something, the backend import is the same one the notebooks use.
