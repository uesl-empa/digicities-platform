# External modules

The platform can load UI modules that live **outside this repo**: you clone the
platform, clone a module repo next to it, point the platform at it, and the
module appears in the sidebar navigation. Modules do not ship with the platform.

## Loading a module

```bash
git clone https://github.com/uesl-empa/digicities-platform.git
git clone <module-repo>                      # e.g. digicities-onboarding-agent

cd digicities-platform
cp .env.example .env
echo "MODULES_HOST_PATH=../<module-repo>" >> .env   # or clone into ./modules/ instead
docker compose up -d --build
```

`MODULES_HOST_PATH` may point at a single module repo or a folder containing
several. Without it, the bundled (empty) `./modules/` folder is mounted, so a
stock install is unchanged. On startup the compose override installs each
mounted module's `requirements.txt` into the container, then Streamlit starts;
every discovered module gets a sidebar nav entry.

If a module declares required environment variables (e.g. an API key), add them
to `.env` — the module's README says which.

## Writing a module

A module is a folder with a `module.yaml` manifest next to a Python package:

```
my-module/                  # ← the module folder (usually its own git repo)
├── module.yaml             # manifest (below)
├── requirements.txt        # extra pip deps beyond the platform's (optional)
├── README.md
└── my_module/              # the package named by `entry`
    └── __init__.py         # exposes the entry function
```

`module.yaml`:

```yaml
name: my-module              # required, unique id
label: "My Module"           # sidebar label (default: name)
description: One-line purpose.
entry: my_module             # required — importable package in the module folder
function: render             # callable in `entry` (default: render)
requires_env: [SOME_API_KEY] # env vars that must be set, checked before render
```

The entry function has the same contract as the platform's built-in components:

```python
def render(client) -> None:
    """client: the workspace-scoped triplestore client (backend.graphdb.client
    .UnifiedGraphDBClient), backend-aware (Fuseki or GraphDB). May be None when
    no triplestore connection exists — handle that."""
```

The module runs inside the platform's Streamlit process, so it can:

- read `st.session_state` — notably `current_workspace` (dict with `id`, `name`,
  …) and `workspace_context` (the registry's `WorkspaceContext`: `.storage` for
  file I/O, `.graphdb_repository`);
- import `backend.*` (the platform root is on `PYTHONPATH`) — e.g.
  `backend.graphdb.graphs` for the canonical named-graph IRIs and
  `from_clause()`, which every SPARQL query should use so it behaves the same on
  Fuseki and GraphDB;
- import the platform's converters and builders rather than re-implementing them.

Rules of thumb for module authors:

- **Query with explicit `FROM` clauses** (`backend.graphdb.graphs.from_clause`).
  Clause-less queries return nothing on Fuseki (no union default graph).
- **Never write to the default graph**; use the canonical named graphs.
- **Route file I/O through `ctx.storage`** where possible so the module works on
  both local-filesystem and NextCloud storage backends.
- Extra dependencies go in the module's own `requirements.txt`; keep them
  permissively licensed.

## How it works

`apps/streamlit/external_modules.py` scans `MODULES_DIR`
(default `/app/data/modules`, mounted from `MODULES_HOST_PATH` by
`docker-compose.override.yml`) for `module.yaml` manifests, adds each label to
the module selector, and imports + calls the entry function when selected.
Import errors and missing env vars are reported in the UI without affecting the
rest of the platform.
