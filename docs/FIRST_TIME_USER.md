# Your first 10 minutes with Digicities

You've heard about Digicities. You want to see what it does. You don't want to read a manual.

This guide gets you from zero to "I see what this is" in ten minutes. No coding. No RDF knowledge. No SPARQL. Just clicks.

> 📘 This is a light no-code tour of the **energy-simulation** demo. It ends by
> pointing you at the fully-tested end-to-end pipeline (build a scenario, submit it
> to the bundled energy simulator, get results back), which is written up
> step-by-step in [`GETTING_STARTED.md`](GETTING_STARTED.md).

---

## Before you start

You need three things:

- **Docker Desktop** installed and running. ([Get it here](https://www.docker.com/products/docker-desktop/) if you don't have it.)
- **Git** installed. ([Get it here](https://git-scm.com/downloads).)
- A terminal. PowerShell on Windows, Terminal on macOS/Linux.

That's it. You don't need Python or any libraries. Everything runs inside Docker.

---

## Step 1: get the code (2 minutes)

In your terminal, go to wherever you keep your projects and run:

```bash
git clone https://github.com/uesl-empa/digicities-platform.git
cd digicities-platform
cp .env.example .env
```

The `cp` copies a default config. You don't need to edit it.

---

## Step 2: start everything (2 minutes)

Still in the same terminal:

```bash
docker compose up -d
```

Docker pulls the images and starts three services. **This takes 2-3 minutes the first time** because it's downloading several hundred megabytes. After that it's instant.

When it's done, your terminal returns to a prompt. Check everything is healthy:

```bash
docker compose ps
```

You should see all three services as `healthy`:

| Service | What it is | URL |
|---|---|---|
| `digicities-streamlit` | The web app you'll use | http://localhost:8501 |
| `digicities-fuseki` | The knowledge graph database | http://localhost:3030 (admin/admin) |
| `digicities-fuseki-init` | A one-shot setup helper (will show "exited 0") | n/a |

If any show as "starting" or "unhealthy", wait 30 seconds and try `docker compose ps` again.

---

## Step 3: open the app (30 seconds)

Open your browser and go to:

**http://localhost:8501**

You'll see a page titled **"Your Workspaces"** with a bundled demo card: **"Energy Simulation (demo)"** (at [`demo_workspaces/`](../demo_workspaces/)). This tour uses it. `docker-compose.override.yml` mounts `./demo_workspaces` into the container automatically.

If you'd rather work against your own usecase repos instead of the demo, edit `docker-compose.override.yml` and change `./demo_workspaces` to point at the parent directory of your usecases (e.g. `../usecases`). Then `docker restart digicities-streamlit`.

---

## Step 4: click around (5 minutes)

This is where you actually look at the platform.

### 📂 Open the workspace

Click the green **"Open"** button on the Energy Simulation card. You're now "inside" that workspace. The sidebar on the left lists modules you can use.

### 🔬 Look at the data: Digital Replica Explorer

In the sidebar, find **"Digital Replica Explorer"** (or "Component Explorer"). Click it. You'll see a list of component types. At the top should be **"Building (4 instances)"**.

Click Building. You'll see a table with four rows, one per building, and columns for each attribute (floor area, building age, number of floors, heating supply, ...):

| building | floor area | age | floors |
|---|---|---|---|
| MFH_1 (multi-family house) | 284 m² | 1985 | 4 |
| Office_1 | 600 m² | 1995 | 5 |
| SFH_1 (single-family house) | 150 m² | 2005 | 2 |
| SFH_old | 180 m² | 1955 | 2 |

> 🧠 **What you're seeing**: a digital twin of four buildings, modelled as RDF triples. The platform reads them from a knowledge graph (Fuseki) and lays them out in a table for you. You didn't have to know what RDF is. Notice each numeric value carries a **unit** (m², yr) — those come from the ontology, so the data is self-describing.

### 🌐 Look at the schema: Ontology Manager

Click **"Ontology Manager"** in the sidebar. Then click the green **"Load Extensions"** button.

You'll see a file called `energy_sim_extension.ttl`. That's the *vocabulary* the building data uses. Definitions like "what's a Building?", "what's a GroundFloorArea attribute, and what unit does it default to?". Click on it to expand.

> 🧠 **What you're seeing**: the schema (the rules) that the data follows. You can edit it from this UI to add new types. For now, just notice that the platform separates *what the words mean* (schema) from *what's true about each building* (data).

### 🧪 Look at the what-ifs: Scenario Builder

Click **"Scenario Builder"** in the sidebar. A scenario is a selection of buildings plus optional *what-if overrides* layered on top of the ingested data — it references the replica, it doesn't copy it.

The workspace ships with a few:

- **Energy Sim - Baseline** — a single building as-ingested.
- **Heat pump retrofit** — the same building with its **HeatingSupply** and **DHWSupply** overridden (an electrified retrofit).
- **Town block** — three buildings together.

Open one and notice the overrides sit *on top of* the baseline values without changing them.

> 🧠 **What you're seeing**: how Digicities models change. A retrofit doesn't overwrite your data — it layers a new attribute that *supersedes* the old one, so you can compare before and after.

---

## The payoff: run it end-to-end

Everything above is the *inputs*. The energy-simulation demo also ships a **fully offline, tested pipeline** that turns a scenario into results:

```
Digital replica  →  Scenario  →  Convert  →  Submit  →  Results dashboard
```

You drive it from **API Data Submission**: the bundled **`demo_energy_simulator`** service auto-registers (no setup), you pick a scenario and **Convert** it to the service's payload, then **Submit** to get annual heating / hot-water / electricity estimates per building.

👉 The click-by-click walkthrough is **Pipeline 1** in [`GETTING_STARTED.md`](GETTING_STARTED.md).

---

## That's it: you've seen the platform

What you just did covers the user-facing workflow:

```
Workspace
  ↓
  ├── Look at the data         (Digital Replica Explorer)
  ├── Look at the schema       (Ontology Manager)
  ├── Define what-if scenarios (Scenario Builder)
  └── Submit to a model        (API Data Submission → results)
```

Plus a couple of things you didn't have to touch yet:

```
  ├── Convert a spreadsheet into workspace data   (Replica Builder)
  └── Layer numeric assumptions onto attributes   (Assumptions Module, archived)
```

Each is one click in the sidebar when you're ready.

---

## What's a workspace, really?

A workspace is **a folder of files** describing one project: your district, your wind farm, your building portfolio, whatever. The platform reads the folder and gives you the UI you just clicked through.

The folder layout is:

```
my-project/
├── ontology/extensions/    your project's vocabulary
├── ingestion/output/       your project's data (RDF/TTL files)
├── scenarios/              what-if scenarios
├── services/               packaged analyses
├── queries/                saved SPARQL queries
├── private_data_products/  curated datasets
└── workspace_meta/         name, description, thumbnail
```

You collaborate by sharing the folder (usually as a git repo). Whoever opens it in their own Digicities platform sees exactly what you see.

---

## When you're ready to build your own

The next step is to create your own workspace. Read:

- **`BEGINNER_GUIDE.md`** in the [usecase template repo](https://github.com/uesl-empa/digicities-usecase-template). A 30-minute walkthrough that takes you from zero to a working workspace with your own data and scenarios.

Or look at:

- **[`GETTING_STARTED.md`](GETTING_STARTED.md)**: the two supported end-to-end pipelines, step by step.
- **[`USECASE_QUICKSTART.md`](USECASE_QUICKSTART.md)**: reference documentation once you know what you're doing.
- **[`WORKSPACE_LAYOUT.md`](WORKSPACE_LAYOUT.md)**: the canonical folder structure spec.
- **[`INFERENCE.md`](INFERENCE.md)**: how the platform's RDFS-Plus inference works and what it means for SPARQL queries.

---

## When you want to stop

```bash
cd digicities-platform
docker compose down
```

That stops all three services. Your data stays in Docker volumes. `docker compose up -d` brings everything back exactly as you left it.

To completely remove everything (data included):

```bash
docker compose down -v
```

---

## If something doesn't look right

| Symptom | Try this |
|---|---|
| `http://localhost:8501` doesn't load | Run `docker compose ps`. All services should say "healthy". If "starting", wait 30 seconds. If "unhealthy", run `docker compose logs streamlit` and look at the last 20 lines. |
| "Your Workspaces" page is empty | Confirm `demo_workspaces/energy-simulation/` exists in your clone (it ships with the repo). Confirm `docker-compose.override.yml` still has the `./demo_workspaces:/app/data/usecases` line and the `USECASES_DIR` env var. Restart Streamlit: `docker restart digicities-streamlit`. |
| "Module not found" error in the UI | Container was built before some dependency was added. Run `docker compose build streamlit && docker compose up -d`. |
| Digital Replica Explorer says "No component types with instances" | Open the workspace first by clicking *📂 Open* on the card. That triggers the data load into Fuseki. Then go to Digital Replica Explorer. |
| Port already in use | Another stack is using port 8501 or 3030. Stop it: `docker ps` to find it, `docker stop <name>`. |

---

That's the platform. Welcome aboard.
