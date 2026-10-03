# Changelog

All notable changes to the Digicities platform are recorded here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **External module loader — UI modules can now live in their own repos and load into a running platform.** A folder with a `module.yaml` manifest (name, label, `entry` package, entry `function`, `requires_env`) mounted via `MODULES_HOST_PATH` (or cloned into the bundled `modules/`) gets a sidebar nav entry; the compose override installs each module's own `requirements.txt` at container start. Entry contract matches built-in components (`fn(client)`, session-state + `backend.*` access). First module: [`digicities-onboarding-agent`](https://github.com/uesl-empa/digicities-onboarding-agent). See `docs/EXTERNAL_MODULES.md`; loader in `apps/streamlit/external_modules.py`.
- **Ontology term index vendored** at `data/ontology/term-index.{json,md}` (generated from core v0.2.0 in `digicities-ontology`), so agents and humans can map domain concepts by annotations without network access or an ontology-repo clone. The agent-facing docs (`AGENTS.md`, `onboarding-kit/AGENTS.md`, `docs/ONBOARDING_A_USECASE.md`) now point at the local copy and give the ontology repo's URL (previously referenced "the ontology repo" with no address).
- **Service configuration (core ontology v0.5.0).** Settings a model needs to run (a model choice, a calibration constant, a run name, a stream address: anything that sets a boundary condition of a run) are recorded as `ConfigurationAttribute` values in a `ServiceConfiguration` profile owned by the service, with `appliesTo` naming the components a profile is tuned for. Profiles live in `services/<Name>.ttl` and are loaded into a new `<http://services>` named graph. The explorer API returns the configuration that applies to a component type's instances (`config_columns`, `configuration`, `has_config` on `GET …/components/{name}`) and lists every profile (`GET …/configurations`). Collections never offer statistics over configuration. The vendored core (both copies, `VERSION` v0.5.0) also declares `derivedFromCatalogue` and `isCatalogueEntry`, which were previously declared per workspace or not at all.
- **Statistics over linked components as service inputs.** A service template can ask for `<Container>.<Attribute><Statistic>` (for example `Tree.WeightMean`, `Tree.WeightStandardDeviation`, `Tree.WeightCount`) and list it under the new `derived_attributes` key. Scenario requirements skip derived attributes (they only exist once computed), and `POST …/submission/convert` now computes them first, like the Streamlit Convert tab.
- **Global asset libraries vendored — a fresh clone shows content fully offline.** `data/global_open_data_products/` ships the **MotelDB** starter product (technology reference database with DOI-cited cost/efficiency attributes, generated from `data/ingestion/input/MotelDB.xlsx`), and the Replica Builder's "Get Template" lookup now falls back to the tracked `data/ingestion_template/data_ingestion_template.xlsx` (no binary duplication; `REPLICA_BUILDER_TEMPLATE_FILE` and a `data/global_replica_builder/` drop-in still take precedence). `.env.example` documents `GLOBAL_SERVICES_DIR` / `GLOBAL_DATA_PRODUCTS_DIR` / `REPLICA_BUILDER_TEMPLATE_FILE`; guarded by `tests/test_global_assets.py`.

- **REST API for the React frontend** (`apps/api`, FastAPI): workspaces, explorer, queries, ontology, replica, scenarios (build, validate against a service, push, delete, drafts), service requirements and registration, submission (convert, validate, submit over HTTP or Redis, persisted results), files (including downloads without the 2 MB cap), collections and the onboarding agent (sessions, SSE streaming, uploads that accumulate into the working folder, decision mode, per-user API keys). A frozen OpenAPI snapshot fails CI on unplanned surface changes; Swagger carries tag descriptions.
- **Backend separation.** The logic behind the Streamlit pages (explorer, scenario emitter, Service Requirements Builder, Replica Builder, data products, workspace lifecycle, Keycloak auth) lives in `backend/`, so the API and Streamlit share it.
- **Accounts and private deployment.** A workspaces database (metadata catalog, Alembic migrations, admin seeding), JWT accounts with workspace ownership and private/shared visibility, workspace assignment, cached and paginated workspace listings, and a single public port. Merges to `main` build and deploy to the cluster automatically.
- **NextCloud storage.** NextCloud is the persistent store of an installation (one store per installation); the API works on a local mirror and publishes changes after every write.
- **Collections**: sets, grouped sets and descriptive statistics over attribute values, materialized into `<http://collections>`; a statistic grouped by component is projected onto the component so services can request it.
- **Scenario sync**: a change to a service cascades onto the scenarios built for it.
- **Explorer**: catalogue / reference entries are identified for the UI filter, and parent classes can optionally be listed.
- **Core ontology v0.4.0** (Observation classes), with both vendored copies kept identical by a test.
- **Service templates**: a running service can name the field that carries an instance's id; a top-level block can be reached through a component link.
- **Ontology extension edits** follow naming rules and one safe sequence of operations; parent-class suggestions match noun phrases by their head noun.

### Fixed
- Chat streams no longer die during long builds (SSE heartbeat); agent sessions are scoped to their own workspace; the agent can add files to a kept working folder after a restart.
- Zero-valued required attributes no longer drop components from scenarios; payloads are complete after one build.
- The NextCloud mirror push runs off the event loop; the API refuses to start when login is enforced on the public development secret; an empty `JWT_SECRET` no longer breaks login; the Postgres driver is named explicitly (SQLAlchemy 2.1 broke sign-in).
- Use-case-specific hardcodes were removed from backend logic, and a CI guard keeps them out.
- **Only the last statistic survived** when a template asked for several statistics of one attribute (a mean and a standard deviation): each was materialized separately into the same collection and replaced the previous one. They are now projected in one pass, and a projected count no longer carries the members' unit.
- **An agent upload froze the whole API.** The upload route was `async def` and ran the minutes-long mapping proposal on the server's single event loop, so the health probe timed out, the API was restarted and every in-memory chat session was lost ("Stream error, is the API running?"). Upload, workbook import and ontology upload now run in a worker thread, and a test fails on any `async def` route.

## [0.4.0] — 2026-07-28

Ontology-alignment release: the platform now runs on the self-describing core ontology v0.2.0, with every term it writes or requires declared upstream, and the assumptions module emits thin scenarios.

### Added
- **Serialiser regression tests** — `tests/test_thin_scenario_ttl.py` locks the thin-scenario contract (override shape, anchoring, historical `linksInputyEntityTo` spelling, full materialisation round-trip with replica inheritance); `tests/test_unit_code_roundtrip.py` pins the QUDT unit-code fix.

### Changed
- **Vendored core ontology synced to v0.2.0** (`data/ontology/` + `services/graphdb/ontology/`, byte-identical mirrors of `digicities-ontology` core). v0.2.0 is the annotation release: every term self-describes via `rdfs:label`/`rdfs:comment` (+ SKOS on mapping-decision classes), the TTL declares `owl:versionInfo "0.2.0"`, and **every term the platform writes or requires is now declared in core** — including `supersedesAttribute`/`basedOn` (thin scenarios), `hasDefaultTemporalPrecision`, `AnnotationAttribute`/`hasAnnotationValue`, and `Reference`/`ReferenceType`/`hasReferenceType`/`DOI`. Domain concepts should be mapped to classes by these annotations (see the ontology repo's `docs/AGENT_MAPPING_GUIDE.md` and `docs/term-index.json`), not by name-matching.

- **Assumptions module now emits *thin* scenarios.** What-if variants reference the replica's components and carry only `dici_onto:supersedesAttribute` overrides for the attributes you changed — the same shape as Scenario Builder / hand-authored scenarios — instead of re-serialising every attribute into a self-contained copy. Unchanged attributes (including resource data paths, curves, and categorical values) inherit from the replica via `materialize_scenario_graphs`, so a partial edit still yields a complete, submittable scenario. Generation is now a single backend serialiser (`backend/assumptions/thin_scenario_ttl.py`); three dead modules were removed.
- **Manual categorical edits are constrained to the ontology's valid values** (named individuals *and* subclass values), matching the Replica Builder, instead of free text. New query `backend.graphdb.queries.ontology.get_categorical_value_options`.
- The Assumptions "Select Components to Modify" list now shows only real replica components (attribute / link / value-class nodes were leaking in).

### Removed
- Dead mock-era modules `apps/streamlit/utils/{workspace_manager,auth_manager,data_processing}.py` (unimported since the `backend/workspace/` registry took over; carried hardcoded mock credentials and endpoints).

### Fixed
- `setup.py` version metadata caught up with the released tags (was stuck at `0.1.0`), and `.env.example` now lists `KEYCLOAK_CLIENT_SECRET`, which `apps/streamlit/components/auth.py` reads when auth is enabled.
- **Scenario and assumptions TTL now emit correct QUDT units instead of `UNITLESS`.** The workspace TTL loader was down-converting `qudt:unit` IRIs to lossy display abbreviations (`KiloW` → `kW`, `KiloW-HR` → `kW-HR`) that the TTL emitter could not turn back into valid QUDT IRIs. `_map_unit_uri_to_string` now returns the QUDT code, so units round-trip cleanly (`qudt:unit unit:KiloW`); `UNITLESS` is emitted only for genuinely unit-less attributes.

## [0.3.0] — 2026-07-16

First public open-source release of the Digicities platform (Apache-2.0).

### Added
- **`backend/scenario_builder/`** — headless scenario TTL generation (`build_scenario_ttl`), closing the previous UI/session-state-only gap in the onboarding pipeline. Covered by `tests/test_scenario_builder.py`.
- **Replica viewer** — full-replica and per-component TTL download buttons.
- **Sidebar Light/Dark "Appearance" toggle** (`styles.render_appearance_toggle`) with readable dark-mode overrides, plus a pinned light default via `.streamlit/config.toml` (Streamlit 1.59 dropped the native toggle).
- **Local-first workspace loading** — mount a folder (or folder of folders) of workspaces via `USECASES_HOST_PATH`; every template-structured subfolder is auto-discovered next to the bundled demos.
- CI workflows validating every docker-compose overlay combination (`compose-config`) and a cross-backend smoke test.

### Changed
- **All workspace file I/O now routes through a single storage abstraction** (`ctx.storage` / `WorkspaceStorage`), giving byte-identical behaviour on local disk and NextCloud. Global assets (service library, open data products, replica-builder template) gained env-overridable local fallbacks (`data/global_*`).
- **Backends are opt-in overlays** — `.env` defaults to local storage + Fuseki; NextCloud (AGPL) and GraphDB Free (proprietary EULA) are opt-in via their compose overlays. A `backend/triplestore/` abstraction hides per-server URL differences.
- **Triplestore-related UI labels** renamed from "GraphDB" to "Triplestore"; the Fuseki web UI now loads without a login in local dev.
- **Ontology extension model — extensions now live in workspaces, not in a central holding area.** The `digicities-ontology` repo is core-only; extensions are authored in each workspace's `ontology/extensions/` in the `dici_onto:` namespace (same as core). Concepts that get adopted across multiple workpackages and prove stable get promoted into core via a PR against `digicities-ontology/core/dici_onto_core.ttl`. See [`digicities-ontology/docs/CORE_EVOLUTION.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/CORE_EVOLUTION.md) for the lifecycle, promotion criteria, and the service-compatibility contract.
- **Ontology Manager → Propose Upstream** form reframed: it now targets `core/dici_onto_core.ttl` for the promote-to-core PR rather than `extensions/<file>`. Pre-PR checklist updated to require ≥2-workpackage adoption + stability before submitting.
- Bumped the base image to **Python 3.11** (from 3.9, which is past its official EOL).

### Docs
- `README.md`, `docs/INFERENCE.md`, `docs/USECASE_QUICKSTART.md` updated to reference the new ontology model + the `CORE_EVOLUTION.md` lifecycle.
- `.env` is git-ignored; `cp .env.example .env` is the documented first step.
- `.env.example` comment for `DIGICITIES_ONTOLOGY_REPO` updated to reflect the promote-to-core target.

### Known limitations
- Container image not yet published to a registry — the [`digicities-usecase-template`](https://github.com/uesl-empa/digicities-usecase-template) `docker-compose.yml` references a placeholder tag; build from a sibling clone (`build: ../digicities-platform`) in the meantime.

## [0.1.0] — 2026-05-23

First tagged release of the Digicities platform.

### Added
- Streamlit UI (`apps/streamlit/`) with Replica Builder, Ontology Manager, Scenario Builder, Assumptions, Data Products, and API Submission modules.
- Pure-Python backend (`backend/`) — `graphdb/`, `ontology_manager/`, `replica_builder/`, `assumptions/`, `data_products/`, `api_submission/`.
- Docker stack (`docker-compose.yml` + override + nextcloud overlay) — Fuseki on `:3030` (GraphDB optional overlay on `:7201`), Streamlit on `:8501`, optional NextCloud on `:8080`.
- Zero-credential local quickstart — `AUTH_DISABLED=true` and `LOCAL_WORKSPACE=workspace_demo` defaults.
- Tutorial notebooks under `tutorial/` against a fictional Alpine Village dataset.
- Excel ingestion pipeline at `data/ingestion/ingest.ipynb`, plus production-ready template at `data/ingestion_template/`.
- Vendored Digicities ontology under `services/graphdb/ontology/` (pinned to `v0.1.0` via `services/graphdb/ontology/VERSION`).
- *Propose Upstream* affordance in the Ontology Manager — exports an extension TTL ready for PR-submission to the upstream ontology repo.
- `NOTICE` and `THIRD_PARTY_LICENSES.md` covering bundled assets and pulled container images.

### Licensing
- Platform code: [Apache License 2.0](LICENSE) (chosen over MIT for the explicit patent grant).
- Vendored ontology and QUDT unit list: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see `NOTICE`.
- GraphDB Free (pulled at runtime, not redistributed) remains proprietary under Ontotext's EULA.

### Known limitations
- Container image not yet published to a registry — the [`digicities-usecase-template`](https://github.com/uesl-empa/digicities-usecase-template) `docker-compose.yml` references `ghcr.io/uesl-empa/digicities-platform:v0.1.0` as a placeholder; uncomment its `build: ../digicities-platform` block to build from a sibling clone meanwhile.
- Python 3.9 base image — past official EOL (October 2025). Functional, but a bump to 3.11+ is planned. *(Done in 0.3.0.)*
- No automated end-to-end test suite yet — the tutorial notebooks are the de-facto regression tests, as documented in `CONTRIBUTING.md`.

### Tooling
- The v0.1.0 release scaffolding — license audit, CI workflows, NOTICE/THIRD_PARTY_LICENSES, deployment documentation — was prepared with assistance from [Claude Code](https://claude.com/claude-code).
