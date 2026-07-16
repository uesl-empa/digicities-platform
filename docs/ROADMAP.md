# Roadmap and future work

Ideas worth picking up once the platform is stable and running end to end. None of
these are blockers for the current release. They are grouped roughly by theme.

The guiding direction across all of them: **configuration should happen in the GUI,
not by editing `.env` and restarting.** The NextCloud connector (sidebar) is the
first example of this pattern; the items below extend it.

## 1. Configurable core-ontology source

Today the platform ships a frozen copy of the core ontology in
`data/ontology/dici_onto_core.ttl`, and the Ontology Manager auto-loads it. This
couples the platform to whatever ontology version shipped with it.

Let the user choose where the core ontology comes from, so they can stay current
without waiting for a new platform release:

- **Workspace / vendored copy** (default). Always works, no network. The offline-safe
  baseline.
- **GitHub release.** Pull a specific tagged version from
  `uesl-empa/digicities-ontology` (`core/dici_onto_core.ttl`), defaulting to the
  latest. Fetch, cache into the global ontology dir, then reload into the
  `<ontology_dici_onto>` graph.
- **GraphDB.** Use whatever ontology is already loaded in the connected
  triplestore. Most useful for a shared or remote GraphDB where an admin has loaded
  a canonical version centrally.

Why: makes `digicities-ontology` the single source of truth, supports reproducibility
(you know which version a graph used), and closes the loop with the existing "Propose
Upstream" feature (pull latest, extend, propose, released, pull latest).

Design notes:
- Offline first. Never block startup on a network call; fall back to the vendored copy.
- Pin the chosen version per workspace (store it in `workspace_meta`) so a project does
  not silently shift ontology versions mid-way.
- Show the active ontology version in the UI, and warn when sources disagree (for
  example GraphDB has v0.1 but an extension references v0.2 classes).
- Needs `digicities-ontology` to be reachable — public, or a token / configurable repo
  URL if it is not yet public in your setup.

Suggested phasing:
1. GitHub-release fetch (tag picker, default latest) with vendored fallback. Show the
   active version.
2. Per-workspace version pinning and mismatch warnings.
3. The "from GraphDB" read path.

Implementation fits the same "source selector" pattern as the NextCloud connector: a
small backend resolver plus a selector in the Ontology Manager.

## 2. More GUI connectors

Follow the NextCloud connector pattern (`backend/workspace/connections.py` + the sidebar
panel) for other backends, so none of them need env editing:

- **GraphDB / triplestore endpoint.** Point the platform at a different GraphDB or
  Fuseki from the GUI, with a connect-and-test button.
- **S3 / object storage** for workspace files (the storage layer already supports fsspec
  backends; this just needs a GUI to enter credentials).

## 3. Workspace management

- **Delete or archive a workspace** from the landing page, to clean up test workspaces
  (removes the folder, the triplestore dataset, and any registry entry). Handy now that
  workspaces can be created from the GUI.
- Optionally an **edit-metadata** action (rename, change description, tags).

## 4. Local NextCloud: service-only overlay

The current `docker-compose.nextcloud.yml` overlay starts NextCloud *and* forces the
Streamlit service into NextCloud-only storage mode (`STORAGE_BACKEND=nextcloud`). With
the GUI connector, NextCloud is opt-in per session, so that env injection is usually not
wanted. Add a lightweight overlay that starts only the NextCloud service (and its init
sidecar) on the same network, leaving the Streamlit env untouched. For now this is done
by hand:

```
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.nextcloud.yml up -d nextcloud nextcloud-init
```

## 5. Smaller polish

- Surface the active ontology version and the active storage backend somewhere obvious
  in the UI (a small status line).

## Reconnect the CESAR-P service

The CESAR-P energy-simulation quick-setup entry point was removed from the API
submission UI for now: it needs more work before it is dependable (it expects a
running local simulation endpoint). Reconnect it - ideally as a declarative service
template like FlexibilityOptimizer, rather than a hardcoded quick-setup button - once
it has a tested, reproducible endpoint to point at.
