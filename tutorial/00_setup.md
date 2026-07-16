# 00 — Setup

Bring up the local stack and load the tutorial sample data.

## One-shot launcher

If you'd rather not run each step by hand, the repo ships a launcher that does the whole thing:

```bash
python tutorial/start_tutorial.py
```

It runs `docker compose up -d`, waits for Fuseki to be healthy, creates the `workspace_demo` dataset, loads the core ontology plus `sample_data/alpine_village.ttl`, and opens Jupyter Lab on `01_ontology_basics.ipynb`. The sections below describe what the launcher is doing under the hood (and are what you'll run if you prefer to drive each step yourself).

## 1. Start the services

From the repo root:

```bash
cp .env.example .env      # local-dev defaults; AUTH_DISABLED=true by default
docker compose up -d
```

This starts two containers:

| Service | Port | What it does |
|---|---|---|
| `digicities-fuseki` | `3030` | Apache Jena Fuseki (the default triplestore) |
| `digicities-streamlit` | `8501` | The main Streamlit UI |

Check they came up healthy:

```bash
docker compose ps
curl http://localhost:3030/$/ping                    # Fuseki: 'pong'
curl -I http://localhost:8501                        # HTTP/1.1 200
```

Fuseki is the default triplestore (`http://fuseki:3030` inside the Docker network). To use
Ontotext GraphDB instead, add the `docker-compose.graphdb.yml` overlay (see the header of
`docker-compose.yml`); it exposes GraphDB on **`7201`** (host) / `graphdb:7200` (container), and
you set `TRIPLESTORE_BACKEND=graphdb` + `GRAPHDB_URL=http://localhost:7201` for host-side notebooks.

## 2. Set up Python for the notebooks

The notebooks import from the repo's `backend/` package directly, so install the project in editable mode:

```bash
pip install -e .
pip install jupyter
```

Alternatively, use the Streamlit container's Python:

```bash
docker exec -it digicities-streamlit bash
cd /app
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root
```

Then forward port 8888 to your host.

## 3. Point Python at the triplestore

The backend client is backend-agnostic — it reads `TRIPLESTORE_BACKEND` (which store) and `GRAPHDB_URL` (where) from the environment. Each notebook's first cell already sets sensible defaults for the host-side Fuseki, so you normally don't need to do anything here. For reference, those defaults are:

```python
import os
os.environ.setdefault("TRIPLESTORE_BACKEND", "fuseki")
os.environ.setdefault("GRAPHDB_URL", "http://localhost:3030")
# Fuseki requires HTTP Basic admin auth for writes (upload / SPARQL update).
# These match the docker-compose defaults.
os.environ.setdefault("FUSEKI_ADMIN_USER", "admin")
os.environ.setdefault("FUSEKI_ADMIN_PASSWORD", "admin")
```

For notebooks running inside the container, leave these unset — the compose file already sets `TRIPLESTORE_BACKEND=fuseki`, `GRAPHDB_URL=http://fuseki:3030`, and the Fuseki admin credentials.

## 4. Load the tutorial sample data

The Alpine Village dataset lives at [`sample_data/alpine_village.ttl`](sample_data/alpine_village.ttl). Notebook 01 loads it into a **named graph** called `https://digicities.info/tutorial/alpine_village`, so it stays isolated from the rest of the `workspace_demo` dataset. The launcher (or the manual step below) *also* loads the core ontology into the dataset's default graph — that's what the ontology-inspection cells in notebook 01 read.

You can also load it manually now:

```python
import os
os.environ.setdefault("TRIPLESTORE_BACKEND", "fuseki")
os.environ.setdefault("GRAPHDB_URL", "http://localhost:3030")
os.environ.setdefault("FUSEKI_ADMIN_USER", "admin")       # Fuseki needs admin auth for writes
os.environ.setdefault("FUSEKI_ADMIN_PASSWORD", "admin")

from backend.workspace.graphdb_provisioning import create_repository, upload_ttl_to_graph

create_repository("workspace_demo", "Digicities tutorial sandbox")

# Core ontology → default graph (bare "" target = the dataset's default graph).
with open("services/graphdb/ontology/dici_onto_core.ttl", encoding="utf-8") as f:
    upload_ttl_to_graph("workspace_demo", "", f.read(), replace=True)

# Alpine Village → the tutorial named graph.
with open("tutorial/sample_data/alpine_village.ttl", encoding="utf-8") as f:
    upload_ttl_to_graph(
        "workspace_demo",
        "https://digicities.info/tutorial/alpine_village",
        f.read(),
        replace=True,
    )
```

## 5. Verify

```python
client.sparql_api_query("""
SELECT (COUNT(*) AS ?triples) WHERE {
  GRAPH <https://digicities.info/tutorial/alpine_village> { ?s ?p ?o }
}
""", out_format="df")
```

You should see roughly 132 triples.

Ready. Continue with [`01_ontology_basics.ipynb`](01_ontology_basics.ipynb).
