# Demo workspaces

Self-contained example workspaces shipped with the platform so that a fresh `docker compose up` has something to show. Each subdirectory is a full, valid workspace following [`docs/WORKSPACE_LAYOUT.md`](../docs/WORKSPACE_LAYOUT.md).

`docker-compose.override.yml` mounts this directory into the Streamlit container at `/app/data/usecases` and sets `USECASES_DIR` accordingly, so anything you drop here shows up in the workspace switcher on the next restart.

## What's here

| Workspace | What it models |
|---|---|
| `energy-simulation/` | The energy-simulation pipeline demo: buildings + scenarios wired to the bundled `demo_energy_simulator` service (convert → submit → dashboard, fully offline). Always available. See `docs/GETTING_STARTED.md`. |
| `motel-energy/` | A small fictional motel chain (3 sites) with an extension TTL, an ingested replica, and two scenarios (baseline + solar rollout). |

## Pointing at your own usecases instead

Edit `docker-compose.override.yml` and change the mount:

```yaml
- ./demo_workspaces:/app/data/usecases   # default
- ../usecases:/app/data/usecases         # your own usecase repos
```

The platform discovers any subfolder with a populated `ontology/extensions/`, `ingestion/output/`, or `scenarios/` directory.
