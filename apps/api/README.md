# Digicities REST API (`apps/api`)

An HTTP seam over the platform's in-process `backend.*` functions, so a separate
front-end (`digicities-frontend`, React) can drive the platform without
Streamlit. This is the backend half of the "off Streamlit" move.

**Round one** covers only the paths the onboarding agent already exercises
headlessly — proof the backend runs without the Streamlit runtime.

## Run

```bash
pip install -r apps/api/requirements.txt          # on top of the platform's own deps
uvicorn apps.api.main:app --reload --port 8000    # PYTHONPATH must include the repo root
```

Interactive docs at `http://localhost:8000/docs`.

The service reads the same env the platform does — `FUSEKI_URL` / `GRAPHDB_URL`
for the triplestore, the workspace registry for workspace resolution.

## Endpoints

| Method | Path | Wraps | Status |
|--------|------|-------|--------|
| GET  | `/health` | — | ✅ live |
| GET  | `/api/workspaces` | `load_registry()` | ✅ live |
| GET  | `/api/workspaces/{id}` | `registry.by_id` | ✅ live |
| POST | `/api/workspaces/{id}/provision` | `ensure_workspace_repo` | ✅ live |
| POST | `/api/workspaces/{id}/query` | `UnifiedGraphDBClient.sparql_api_query` | ✅ live |
| POST | `/api/workspaces/{id}/replica` | `process_excel_to_ttl` | 🚧 501 |
| POST | `/api/workspaces/{id}/scenario` | `build_scenario_ttl` | 🚧 501 |
| POST | `/api/workspaces/{id}/submit` | `convert_scenario` | 🚧 501 |
| GET  | `/api/workspaces/{id}/agent` | onboarding agent (LangGraph, SSE) | 🚧 501 |
| GET  | `/api/workspaces/{id}/collections` | `backend.collections.list_collections` | ✅ live |
| GET  | `/api/workspaces/{id}/collections/options` | attribute/component/dataset choices | ✅ live |
| GET  | `/api/workspaces/{id}/collections/{name}` | statistics + distribution + members | ✅ live |
| POST | `/api/workspaces/{id}/collections` | `materialize_set` / `materialize_grouped_set` | ✅ live |
| DELETE | `/api/workspaces/{id}/collections/{name}` | `delete_collection` | ✅ live |

## Design notes

- **Stateless context.** Streamlit rebuilt `WorkspaceContext` from session state
  each rerun; here `apps/api/deps.py::get_ctx` resolves it per request from the
  workspace registry, keyed by the `{workspace_id}` in the route.
- **No backend changes.** Endpoints call `backend.*` exactly as the Streamlit
  components and the onboarding agent do — this repo adds a layer, it doesn't
  fork the backend.
- **Next:** file-upload for `/replica`, the scenario/submit contracts, and the
  agent as a streamed (SSE/WebSocket) endpoint.
