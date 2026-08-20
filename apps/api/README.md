# Digicities REST API (`apps/api`)

An HTTP seam over the platform's in-process `backend.*` functions, so a separate
front-end (`digicities-frontend`, React) can drive the platform without
Streamlit. This is the backend half of the "off Streamlit" move.

Every module of the React app is served: workspaces, explorer, query manager,
ontology manager, replica builder, service requirements, scenario builder,
API submission, collections, data products, workspace file browsing, and the
onboarding agent (with SSE streaming).

## Run

```bash
pip install -r apps/api/requirements.txt          # on top of the platform's own deps
uvicorn apps.api.main:app --reload --port 8000    # PYTHONPATH must include the repo root
```

Interactive docs at `http://localhost:8000/docs`.

The service reads the same env the platform does — `FUSEKI_URL` / `GRAPHDB_URL`
for the triplestore, `USECASES_DIR` for workspace files, `MODULES_DIR` for the
mounted onboarding-agent module, `LLM_MODEL` for the agent's default model.

## Endpoints

All workspace-scoped paths start with `/api/workspaces/{id}`, shortened to `…` here.

| Method | Path | Wraps |
|--------|------|-------|
| GET  | `/health` | — |
| GET  | `/api/workspaces` | `load_registry()` + `workspace_last_updated` (newest first) |
| POST | `/api/workspaces` | `backend.workspace.create_workspace` |
| GET  | `…` | `registry.by_id` |
| GET  | `…/info` | workspace metadata + activity stamp for the sidebar |
| POST | `…/provision` | `ensure_workspace_repo` |
| POST | `…/query` | `UnifiedGraphDBClient.sparql_api_query` |
| GET  | `…/components`, `…/components/{name}` | Digital Replica Explorer reads |
| GET  | `…/recommendations` | Instance Inspector recommendations |
| *    | `…/ontology/…` (24 routes) | `OntologyFunctions` — extensions, components, attributes, links, categories, named individuals, mappings, export, publish, upload |
| GET  | `…/replica/config`, `…/replica/ttl` | replica project URI / current TTL |
| POST | `…/replica/import` | `process_excel_to_ttl` (multipart .xlsx) |
| POST | `…/replica/generate` | in-app model → workbook → `process_excel_to_ttl` |
| GET  | `…/service/palette` | component types + attributes a service can require |
| POST | `…/service/requirements` | requirements TTL → `services/{Name}.ttl` |
| POST | `…/service/template` | service-template YAML → `services/{Name}.yaml` |
| GET  | `…/scenario/instances`, `…/scenario/list`, `…/scenario/ttl` | scenario palette / saved scenarios |
| POST | `…/scenario/build` | `backend.scenario_builder.build_scenario_ttl` |
| GET  | `…/submission/templates`, `…/submission/scenarios` | submission inputs |
| POST | `…/submission/convert` | `backend.api_submission.ttl_converter.convert_scenario` |
| POST | `…/submission/submit` | HTTP submit to the service endpoint |
| GET  | `…/collections`, `…/collections/options`, `…/collections/{name}` | `backend.collections` reads |
| POST | `…/collections` | `materialize_set` / `materialize_grouped_set` |
| DELETE | `…/collections/{name}` | `delete_collection` |
| GET  | `…/data-products` | `backend.data_products.DataProductProcessor` listings (private + open) |
| GET  | `…/data-products/{name}` | processed product: metadata + components + resources |
| GET  | `…/data-products/{name}/resource?path=` | one resource, parsed (CSV rows capped / GeoJSON / EPW-text head) |
| GET  | `…/files?path=` | workspace directory listing (name, type, size, mtime; traversal-guarded) |
| GET  | `…/files/content?path=` | small-file fetch (≤ 2 MB, guessed content type; traversal-guarded) |
| GET  | `…/agent/models`, `…/agent/chats`, `…/agent/state` | onboarding agent (headless `AgentSession`) |
| POST | `…/agent/session`, `…/agent/model`, `…/agent/message`, `…/agent/upload` | agent lifecycle + turns |
| GET  | `…/agent/message/stream` | SSE: `token` events, then `result`, then `done` |

## Design notes

- **Stateless context.** Streamlit rebuilt `WorkspaceContext` from session state
  each rerun; here `apps/api/deps.py::get_ctx` resolves it per request from the
  workspace registry, keyed by the `{workspace_id}` in the route. Workspace file
  paths come from `deps.ws_root` — routers must not re-derive them.
- **No backend changes.** Endpoints call `backend.*` exactly as the Streamlit
  components and the onboarding agent do — this repo adds a layer, it doesn't
  fork the backend.
- **Agent sessions are in-memory and single-process.** One uvicorn worker only;
  sessions are lost on reload. A turn that fails reports `result["error"]`
  alongside the transcript. Known limits (see the separation plan, Phase 7):
  session eviction, multi-worker support, SSE message via POST body.
- **CORS is dev-open** (`allow_origins=["*"]`). Tighten to the deployed
  frontend origin before this leaves a laptop.
