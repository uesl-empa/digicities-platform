# Setting up a Digicities usecase, step by step

This guide walks you through:

- **Part A**: first-time platform setup on your machine (do once)
- **Part B**: register an existing usecase repo (or one of the bundled demos) as a workspace
- **Part C**: build a brand-new usecase from scratch using the template
- **Part D**: what's wired today and what isn't (set expectations before you test)

Tested on Windows 11 + Docker Desktop + PowerShell. The Docker commands work identically on macOS and Linux. Substitute `~` for `$env:USERPROFILE` and forward slashes throughout.

---

# Part A: platform setup (5 minutes, do once)

## A1. Prerequisites

- **Docker Desktop** running
- **Git** installed
- One free disk location to host platform plus usecases (the examples below assume `C:\dev\digicities-opensource\`)

## A2. Clone the three repos

```powershell
$ROOT = "C:\dev\digicities-opensource"
mkdir $ROOT; cd $ROOT
mkdir usecases

git clone https://github.com/uesl-empa/digicities-platform.git
git clone https://github.com/uesl-empa/digicities-ontology.git    # optional, only needed if you'll update vendored ontology
```

After this you have:

```
digicities-opensource/
├── digicities-ontology/          (optional)
├── digicities-platform/
└── usecases/                     <-- empty for now; workspaces go here
```

## A3. Configure the platform to mount your usecases dir

Edit `digicities-platform/docker-compose.override.yml` to add the usecases bind-mount and the env var that tells the registry where to look:

```yaml
services:
  streamlit:
    volumes:
      - .:/app
      # Mount the usecases parent dir so registered workspaces are visible.
      - C:/dev/digicities-opensource/usecases:/app/data/usecases
    environment:
      USECASES_DIR: /app/data/usecases
    command: >
      streamlit run apps/streamlit/app.py
      --server.port=8501
      --server.address=0.0.0.0
      --server.runOnSave=true
      --server.fileWatcherType=poll
```

(macOS/Linux users: replace the Windows path with `~/digicities-opensource/usecases:/app/data/usecases`.)

## A4. Boot the stack

```powershell
cd digicities-platform
cp .env.example .env
docker compose up -d
```

The first `up` builds the Streamlit image (~3 min). On subsequent runs it's seconds.

## A5. Verify it's healthy

```powershell
docker compose ps                                # all containers should say "(healthy)"
curl http://localhost:3030/$/ping                # Fuseki: 'pong' (GraphDB overlay: :7201)
curl -I http://localhost:8501                    # expect HTTP/1.1 200 OK
```

Open **http://localhost:8501** in your browser. You'll see the *Your Workspaces* page. It's empty. You haven't registered any yet.

---

# Part B: add an existing usecase as a workspace (2 minutes)

This is the fastest way to verify everything works. Use one of the bundled demos.

## B1. Clone the demo into `usecases/`

```powershell
cd $ROOT/usecases
# The bundled demo usecase:
git clone https://github.com/uesl-empa/digicities-usecase-energy-simulation.git energy-simulation
```

> If those repos don't exist yet, you can copy the bundled demos directly from `digicities-platform/demo_workspaces/`. See Part D for the current status.

## B2. Reload the browser

The workspace registry auto-discovers any folder under `usecases/` that has the canonical layout. No restart, no config edits. Just refresh the page.

You should now see a card per cloned usecase on the *Your Workspaces* page.

## B3. Open the workspace

Click **📂 Open** on the workspace card.

You're now "inside" the workspace. The sidebar shows the available modules:

- **Ontology Manager** ✅ wired. Reads and writes the workspace's `ontology/extensions/`.
- **Replica Builder** ⚠️ uses legacy paths (see Part D).
- **Other modules**: same caveat.

## B4. Browse the workspace's extension

Sidebar → **Ontology Manager** → *🔄 Load Extensions*.

You should see the workspace's extension file (e.g. `energy_sim_extension.ttl`). Click *Open* and you can browse the classes and attributes the workspace defines.

Switch workspaces from the sidebar dropdown. The Ontology Manager re-loads with the *other* workspace's extension. This is the proof point: each workspace owns its own ontology view.

---

# Part C: build a new usecase from scratch (15 minutes)

## C1. Instantiate the template

Easiest path: GitHub's *Use this template* button.

1. Open https://github.com/uesl-empa/digicities-usecase-template
2. Click **Use this template → Create a new repository**
3. Name it e.g. `digicities-usecase-my-district`
4. Make it public or private as you prefer

Then clone it into `usecases/`:

```powershell
cd $ROOT/usecases
git clone https://github.com/<your-org>/digicities-usecase-my-district.git my-district
cd my-district
```

If you'd rather not involve GitHub yet, just copy the template:

```powershell
git clone https://github.com/uesl-empa/digicities-usecase-template.git my-district
cd my-district
Remove-Item -Recurse -Force .git
git init
```

## C2. Customise the workspace metadata

Edit `workspace_meta/metadata.json`:

```json
{
  "id": "my-district",
  "name": "My District",
  "description": "Two short sentences describing what this usecase models.",
  "created": "2026-05-25",
  "tags": ["whatever", "is", "useful"]
}
```

Refresh the browser. Your workspace card now shows the new name and description.

## C3. Add an ontology extension

The extension is a TTL file declaring the classes and properties your project needs that aren't already in the core ontology.

Put it at `ontology/extensions/<your-extension>.ttl`. **Extensions live in the same `dici_onto:` namespace as the core.** This keeps queries uniform across core and extensions. A query for `?x a dici_onto:EnergyConsumer` finds your `HighRiseBuilding` instances without needing a UNION over namespaces.

```turtle
@prefix dici_onto: <https://digicities.info/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

dici_onto:HighRiseBuilding a owl:Class ;
    rdfs:subClassOf dici_onto:EnergyConsumer ;
    rdfs:label "High-rise building"@en ;
    rdfs:comment "Residential or commercial building above 8 storeys."@en .
```

The Ontology Manager picks it up immediately, no restart. (You can also author extensions graphically from the Ontology Manager UI. It writes a well-formed TTL into the same dir.)

## C4. Add instance data

Place your replica TTL under `ingestion/output/<name>.ttl`. This is the canonical, ontology-typed form of your replica. Instance URIs live in your project's own namespace (e.g. `https://digicities.info/proj/my-district/Building_A`). Only the *types* and *predicates* come from `dici_onto:`.

If you have a populated Digicities Excel workbook, drop it at `ingestion/input/<name>.xlsx` and convert it via the platform's Excel pipeline (Replica Builder → Excel Import in the UI).

## C5. Define a scenario

A scenario is a snapshot of the world. Create one TTL per scenario under `scenarios/`. Each component you want included is anchored to the scenario via `dici_onto:usedInScenario`:

```turtle
@prefix sc: <https://digicities.info/proj/my-district/scenarios/> .
@prefix dici_onto: <https://digicities.info/ontology#> .

sc:baseline a dici_onto:Scenario ;
    rdfs:label "Baseline (2026-05)" .

<https://digicities.info/proj/my-district/Building_A> dici_onto:usedInScenario sc:baseline .
<https://digicities.info/proj/my-district/Building_B> dici_onto:usedInScenario sc:baseline .
```

The core ontology defines three load-bearing classes for scenario work: `dici_onto:Scenario`, `dici_onto:Assumption` (with `AssumptionSingle` / `AssumptionSeries` subclasses), and the predicate `dici_onto:usedInScenario`. How you layer modifications on top of a baseline (which attribute version applies in which scenario, how alternatives are queried) is a *project-level convention*. The core doesn't prescribe a single pattern. The bundled demo workspaces show one such convention. Adopt or design your own.

## C6. Define a service

Each service is a YAML file under `services/` describing what report or computation it produces, plus a small Python runner under the same dir.

Use the bundled demo as a starting point. Copy `services/` from any demo workspace under `usecases/` (where you cloned the platform) and adapt. The runner pattern is:

1. Load core ontology, workspace's extensions, instance data, and chosen scenario into rdflib.
2. Run SPARQL queries against the merged graph, filtering on `dici_onto:usedInScenario` for scenario-aware selectivity.
3. Write a CSV to `outputs/<scenario>__<service>.csv`.

Run it:

```powershell
cd $ROOT/usecases/my-district
python services/run_service.py scenarios/baseline.ttl services/<your-service>.yaml
```

## C7. Commit and push

```powershell
cd $ROOT/usecases/my-district
git add .
git commit -m "Initial scenarios + service"
git push
```

Your usecase is now a tracked git repo. Anyone who clones it into their own `usecases/` dir gets the same workspace registered in their platform.

---

# Part D: module wiring status (as of v0.3)

## ✅ Fully wired (workspace-aware)

| Concern | Where it reads/writes | Notes |
|---|---|---|
| Workspace registry | `data/workspaces.yaml` + auto-discovery under `$USECASES_DIR` | YAML + auto-discovery merge |
| Workspace switcher (Streamlit sidebar) | Reads the registry; session state holds the `WorkspaceContext` | |
| **Ontology Manager** | Active workspace's `ontology/extensions/`, `ontology/exports/`, `ontology/temp/` | Via `WorkspaceStorage` |
| **Query Manager** | Active workspace's `queries/*.sparql` and `queries/namespaces.txt` | Legacy NextCloud `global/queries/` retained as fallback for pre-v0.2 NextCloud workspaces |
| **Replica Builder** (Excel → TTL) | UI uploads land in workspace's `ingestion/input/<name>.xlsx`. Converted TTL written to `ingestion/output/<name>.ttl`. | Mirror happens automatically on successful conversion |
| **Scenario Builder** (upload to workspace) | Active workspace's `scenarios/<filename>.ttl` | Legacy NextCloud `graph/scenarios/` retained as fallback |
| **Data Products** (folder listing + TTL parsing + resource reads) | Active workspace's `private_data_products/<product>/` (TTL manifest + resources/) | All three layers wired via storage. Works for local and NextCloud workspaces. |
| **Per-workspace triplestore datasets** | One dataset per workspace, lazily provisioned on first open | Loads core ontology, extensions, instance data, scenarios |
| **Standalone service runners** (`usecases/*/services/run_service.py`) | Pure rdflib + vendored core ontology | Workspace-aware via filesystem. Ignore Streamlit/triplestore. |

## ✅ Triplestore layout per workspace

When `open_workspace` is called for the first time, the platform creates a triplestore dataset named after the workspace id and loads:

| Named graph | Source |
|---|---|
| `<http://ontology_dici_onto>` | platform's vendored `services/graphdb/ontology/dici_onto_core.ttl` plus workspace's `ontology/extensions/*.ttl` |
| `<http://instance_data>` | workspace's `ingestion/output/*.ttl` |
| `<http://scenarios>` | workspace's `scenarios/*.ttl` |

Re-opening a workspace re-uploads the current TTLs. File edits show up in SPARQL queries without manual re-provisioning. Auto-provisioning failures degrade gracefully. File-based modules keep working. Only SPARQL needs the repo.

## Triplestore choice: Fuseki (default) or GraphDB Free (opt-in)

As of v0.3, the default triplestore is **Apache Jena Fuseki** (Apache-2.0). The out-of-the-box stack is now 100% OSI-approved. A small `backend/triplestore/` abstraction hides the per-server URL differences so the rest of the platform is backend-agnostic.

| Backend | License | When to use |
|---|---|---|
| **Fuseki** (default) | Apache-2.0 | Strict procurement, public-sector, anyone wanting an unencumbered stack |
| GraphDB Free (opt-in) | Proprietary EULA | You want GraphDB's Workbench UI or built-in inference |

To opt into GraphDB Free, edit `.env`:

```
COMPOSE_FILE=docker-compose.yml;docker-compose.graphdb.yml
COMPOSE_PATH_SEPARATOR=;
TRIPLESTORE_BACKEND=graphdb
GRAPHDB_URL=http://graphdb:7200
```

Then `docker compose up -d`. Workspaces are re-provisioned in GraphDB on first open. The Fuseki container can stay up alongside (different port: 3030). Only `TRIPLESTORE_BACKEND` determines which one the platform talks to.

## ⚠️ Known limitations

- **GraphDB Free EULA** (only relevant under the opt-in overlay): proprietary, not OSI-approved. Fine for local dev and R&D. **Blocks** strict OSI-only procurement. Needs commercial license for embedding in a commercial derivative. The Fuseki default sidesteps all of this.

## NextCloud-backed workspaces

The `nextcloud` backend in `data/workspaces.yaml` is validated against the bundled NextCloud overlay. To enable:

1. Add the NextCloud overlay to `.env`:
   ```
   COMPOSE_FILE=docker-compose.yml;docker-compose.override.yml;docker-compose.nextcloud.yml
   COMPOSE_PATH_SEPARATOR=;
   NEXTCLOUD_BASIC_USERNAME=admin
   NEXTCLOUD_BASIC_PASSWORD=admin
   NEXTCLOUD_BASE_URL=http://nextcloud:80
   ```
2. `docker compose up -d`. `services/nextcloud/init.sh` seeds the canonical `workspace_demo/...` folder tree on first boot.
3. Register the workspace in `data/workspaces.yaml`:
   ```yaml
   workspaces:
     - id: workspace_demo
       name: NextCloud Demo
       backend: nextcloud
       nextcloud_root: workspace_demo
   ```
4. Restart Streamlit. The NextCloud workspace appears alongside any local workspaces.

What works identically for both backends: Ontology Manager, Query Manager, Replica Builder, Scenario Builder, Data Products (folder + TTL + resource reads), workspace switcher.

## What you can test end-to-end today

1. Drop a folder under `usecases/` → ✓ visible in switcher
2. Switch workspaces → ✓ Ontology Manager + Query Manager + Scenario Builder all re-bind
3. Upload an Excel via Replica Builder → ✓ `.xlsx` mirrors into `ingestion/input/` and `.ttl` into `ingestion/output/`
4. Open the workspace → ✓ a dedicated triplestore dataset (named after the workspace id) is created and populated with the workspace's TTLs
5. Run SPARQL queries via the Query Manager → ✓ queries hit the workspace's triplestore dataset, return only that workspace's data
6. Save a scenario from the Scenario Builder → ✓ lands in the workspace's `scenarios/` dir
7. Click *Propose Upstream* on a workspace extension → ✓ opens the GitHub web editor on `digicities-ontology/core/dici_onto_core.ttl` for the promote-to-core PR (see [`CORE_EVOLUTION.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/CORE_EVOLUTION.md) for when to actually use it)
8. Run a service from the workspace's command line → ✓ scenario-aware CSV outputs

---

# Troubleshooting

| Symptom | Fix |
|---|---|
| Workspace doesn't appear in switcher | Confirm the folder has `ontology/extensions/`, `scenarios/`, or `ingestion/output/` populated. Auto-discovery skips empty folders. |
| `ModuleNotFoundError: No module named 'fsspec'` in Streamlit logs | The image was built before fsspec landed in `requirements.txt`. Either `docker compose build streamlit` to rebuild, or quick-fix in dev mode: `docker exec digicities-streamlit pip install fsspec webdav4 && docker restart digicities-streamlit`. |
| `docker compose up` says port 3030 / 8501 already in use | Another Digicities stack is running. Stop it first: `docker stop digicities-fuseki digicities-streamlit digicities-nextcloud && docker rm digicities-fuseki digicities-streamlit digicities-nextcloud`. |
| Streamlit shows "could not load metadata" | The workspace's `workspace_meta/metadata.json` is missing or malformed. Auto-discovery falls back to the folder name as the display name. |
| Workspace edits don't persist | Confirm the `volumes:` mount in `docker-compose.override.yml` points at the *actual* `usecases/` dir on your host, not a typo'd path. |

---

# Reference

- **Canonical workspace layout**: [`WORKSPACE_LAYOUT.md`](WORKSPACE_LAYOUT.md)
- **Registry config schema**: [`data/workspaces.yaml.example`](../data/workspaces.yaml.example)
- **Demo usecase** (in this repo): [`demo_workspaces/energy-simulation/`](../demo_workspaces/energy-simulation/)
- **Usecase template** (use as starting point): https://github.com/uesl-empa/digicities-usecase-template
