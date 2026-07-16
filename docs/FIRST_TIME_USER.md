# Your first 10 minutes with Digicities

You've heard about Digicities. You want to see what it does. You don't want to read a manual.

This guide gets you from zero to "I see what this is" in ten minutes. No coding. No RDF knowledge. No SPARQL. Just clicks.

> 📘 This is a light no-code tour of the **motel** demo. For the supported end-to-end
> pipelines (energy simulation and the flexibility optimiser), follow
> [`GETTING_STARTED.md`](GETTING_STARTED.md). One step below uses the **Query Manager**
> module, which is archived — tick **"Show archived modules"** in the sidebar to follow it.

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

You'll see a page titled **"Your Workspaces"** with two bundled demo cards: **"Roadside Motel Chain"** and **"Energy Simulation"** (at [`demo_workspaces/`](../demo_workspaces/)). This tour uses the motel one. `docker-compose.override.yml` mounts `./demo_workspaces` into the container automatically.

> ℹ️ **Note on naming.** The `motel-energy` demo workspace is a tiny example modelling three fictional motels. It is **not** the same as `MotelDB.xlsx` you may see elsewhere in the codebase. That's a separate *technology database* (an equipment-spec catalogue, not a worked example). Don't conflate the two.

If you'd rather work against your own usecase repos instead of the demo, edit `docker-compose.override.yml` and change `./demo_workspaces` to point at the parent directory of your usecases (e.g. `../usecases`). Then `docker restart digicities-streamlit`.

---

## Step 4: click around (5 minutes)

This is where you actually look at the platform.

### 📂 Open the workspace

Click the green **"Open"** button on the Motel Chain card. You're now "inside" that workspace. The sidebar on the left lists modules you can use.

### 🔬 Look at the data: Component Explorer

In the sidebar, find **"Digital Replica Explorer"** (or "Component Explorer"). Click it. You'll see a list of component types. At the top should be **"Building (3 instances)"**.

Click Building. You'll see a table with three rows, one per motel (A, B, C), and columns for each attribute (floor area, electricity consumption, etc.).

> 🧠 **What you're seeing**: a digital twin of three real-ish motels, modelled as RDF triples. The platform reads them from a knowledge graph (Fuseki) and lays them out in a table for you. You didn't have to know what RDF is.

### 🌐 Look at the schema: Ontology Manager

Click **"Ontology Manager"** in the sidebar. Then click the green **"Load Extensions"** button.

You'll see a file called `motel_project.ttl`. That's the *vocabulary* the motel data uses. Definitions like "what's a Building?", "what's an electricity consumption attribute?". Click on it to expand.

> 🧠 **What you're seeing**: the schema (the rules) that the data follows. You can edit it from this UI to add new types. For now, just notice that the platform separates *what the words mean* (schema) from *what's true about each motel* (data).

### 🔍 Run a query: Query Manager

Click **"Query Manager"** in the sidebar. There's a pre-saved query called `list_motels`. Pick it from the dropdown. You'll see SPARQL code appear in the text box.

Click the **"🚀 Run Query"** button. You'll see a 3-row table:

| building | label |
|---|---|
| https://digicities.info/proj/motel-energy/MotelA | Motel A, Highway Junction |
| https://digicities.info/proj/motel-energy/MotelB | Motel B, Lakeside |
| https://digicities.info/proj/motel-energy/MotelC | Motel C, Mountain Pass |

> 🧠 **What you're seeing**: a live query against the workspace's knowledge graph. SPARQL is to RDF what SQL is to spreadsheets. You don't have to write SPARQL. Workspace authors save common queries for you.

### 📦 Look at a packaged dataset: Data Products

Click **"Data Products"** in the sidebar. You'll see one product: `motel_chain_monthly_electricity`.

Click into it. You'll see a TTL manifest (describing what's in the product) and a CSV file (`monthly_kwh.csv`) with 36 rows: 3 motels x 12 months of electricity consumption.

> 🧠 **What you're seeing**: a "data product", a packaged dataset (a CSV plus a manifest that says what it is, where it came from, what it relates to) that other people can use without having to ask you what the columns mean.

---

## That's it: you've seen the platform

What you just did is the entire user-facing workflow:

```
Workspace
  ↓
  ├── Look at the data         (Component Explorer)
  ├── Look at the schema       (Ontology Manager)
  ├── Ask questions of it      (Query Manager)
  └── Use packaged datasets    (Data Products)
```

Plus three things you didn't have to touch yet:

```
  ├── Convert Excel to workspace data    (Replica Builder)
  ├── Define what-if scenarios           (Scenario Builder)
  └── Submit to external solvers         (API Submission)
```

Each of those is one click in the sidebar when you're ready.

---

## What's a workspace, really?

A workspace is **a folder of files** describing one project: your district, your wind farm, your motel chain, whatever. The platform reads the folder and gives you the UI you just clicked through.

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
| "Your Workspaces" page is empty | Confirm `demo_workspaces/motel-energy/` exists in your clone (it ships with the repo). Confirm `docker-compose.override.yml` still has the `./demo_workspaces:/app/data/usecases` line and the `USECASES_DIR` env var. Restart Streamlit: `docker restart digicities-streamlit`. |
| "Module not found" error in the UI | Container was built before some dependency was added. Run `docker compose build streamlit && docker compose up -d`. |
| Component Explorer says "No component types with instances" | Open the workspace first by clicking *📂 Open* on the card. That triggers the data load into Fuseki. Then go to Component Explorer. |
| Port already in use | Another stack is using port 8501 or 3030. Stop it: `docker ps` to find it, `docker stop <name>`. |

---

That's the platform. Welcome aboard.
