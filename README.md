# Digicities

Digicities is a requirements-driven semantic layer that connects models to the data they need: each model states its inputs as requirements against a shared ontology, and the platform finds, checks and delivers that data from a knowledge graph.

In practice it works like this. You describe your system (a wind park, a district, a building portfolio) once, as components with attributes, in a knowledge graph built on the [Digicities ontology](https://github.com/uesl-empa/digicities-ontology). A model you want to run states what it needs in a service contract, for example `WindTurbine.HubHeight` and a link from each turbine to its wind park. Digicities checks a scenario against that contract, tells you what is missing, and only then sends the model a payload in the shape it asked for.

The platform includes the shared OWL ontology, a web app (React, with the older Streamlit UI still available), a Python backend and REST API, an onboarding agent that turns a folder of model code and data into a workspace, and a triplestore (Apache Jena Fuseki by default).

> **New here?** Start with [`docs/CONCEPTS.md`](docs/CONCEPTS.md) for the ideas, then
> [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md), which takes you from a fresh clone
> through two complete working pipelines (energy simulation and the flexibility optimiser).
> For a quick no-code tour, see [`docs/FIRST_TIME_USER.md`](docs/FIRST_TIME_USER.md).

## Read next

In this order:

1. [`docs/CONCEPTS.md`](docs/CONCEPTS.md): workspace, replica, scenario, service, requirement, collection, and how data moves between them.
2. [`docs/SERVICE_REQUIREMENTS_SPEC.md`](docs/SERVICE_REQUIREMENTS_SPEC.md): the requirements language a model uses to state what it needs.
3. [`docs/SEMANTIC_LAYER.md`](docs/SEMANTIC_LAYER.md): what makes Digicities a semantic layer, and what still has to be done.
4. [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md): what does not work yet, dated and kept up to date.
5. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the code is organised.
6. [`docs/POSITIONING.md`](docs/POSITIONING.md): why Digicities, and not FIWARE, IDS, Brick, SHACL alone, OEO or CESDM.
7. [Linking to established domains](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/LINKING_DOMAINS.md): how to connect the ontology to Brick, OEO, SAREF, BOT, IFC, CityGML and CIM.
8. [`docs/ROADMAP.md`](docs/ROADMAP.md): what comes next.

## Quickstart

```bash
git clone https://github.com/uesl-empa/digicities-platform.git
cd digicities-platform
docker compose up -d --build
```

That starts Fuseki on `:3030` and Streamlit on `:8501`. Open **http://localhost:8501**.
`AUTH_DISABLED=true` is the default (no login), and two demo workspaces are bundled and appear
automatically — so the [energy-simulation pipeline](docs/GETTING_STARTED.md#5-pipeline-1--energy-simulation-fully-offline)
works out of the box.

## Working with your own data

A **workspace** is a folder describing one project (your district, your wind farm, your building portfolio). To load one, point the platform at a directory of usecases:

```yaml
# digicities-platform/docker-compose.override.yml
services:
  streamlit:
    volumes:
      - ../usecases:/app/data/usecases
    environment:
      USECASES_DIR: /app/data/usecases
```

Restart Streamlit, refresh the browser. Any workspace under `../usecases/` appears in the workspace switcher. The canonical workspace layout is in [`docs/WORKSPACE_LAYOUT.md`](docs/WORKSPACE_LAYOUT.md).

To start your own workspace from scratch, use the [`digicities-usecase-template`](https://github.com/uesl-empa/digicities-usecase-template) repo. It ships with a `BEGINNER_GUIDE.md` that takes you from zero to a working workspace in about 30 minutes.

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/FIRST_TIME_USER.md`](docs/FIRST_TIME_USER.md) | 10-minute zero-to-clicking-around tour |
| [`docs/WORKSPACE_LAYOUT.md`](docs/WORKSPACE_LAYOUT.md) | Canonical folder spec for a workspace |
| [`docs/ONBOARDING_A_USECASE.md`](docs/ONBOARDING_A_USECASE.md) | From a messy model + data dump to a submitted scenario (front-to-back) |
| [`onboarding-kit/`](onboarding-kit/) | Model-agnostic AGENTS.md brief to drop into any model+data folder and onboard it with an agent |
| [`docs/USECASE_QUICKSTART.md`](docs/USECASE_QUICKSTART.md) | Reference for building a usecase end-to-end |
| [`docs/INFERENCE.md`](docs/INFERENCE.md) | How RDFS-Plus inference is materialised at workspace open |
| [`docs/INTEGRATING_A_SERVICE.md`](docs/INTEGRATING_A_SERVICE.md) | Onboard a model/service for scenario submission |
| [`docs/EXTERNAL_MODULES.md`](docs/EXTERNAL_MODULES.md) | Load UI modules from their own repos (e.g. the Onboarding Agent) |
| [`docs/sparql_query_reference.md`](docs/sparql_query_reference.md) | SPARQL patterns for the workspace graphs, incl. configuration and derived statistics |
| [`apps/api/README.md`](apps/api/README.md) | The REST API the React frontend uses: endpoints and design notes |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Local vs cloud deployment; NextCloud storage, mirror sync, pre-/post-deploy verification |
| [`AGENTS.md`](AGENTS.md) | Orientation + tool/doc index for automated agents |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute back to this repo |

## Ontology

The schema (`dici_onto_core.ttl` plus QUDT units) lives in [`digicities-ontology`](https://github.com/uesl-empa/digicities-ontology) (CC BY 4.0). A copy is vendored here at [`services/graphdb/ontology/`](services/graphdb/ontology/), so `docker compose up` works offline.

To add new classes or properties for your project, use the **Ontology Manager** in the Streamlit UI. It writes TTLs into your workspace's `ontology/extensions/`. Extensions use the same `dici_onto:` namespace as core, so queries find core and extension terms uniformly.

When a concept has been adopted across multiple workpackages and proven stable, propose it for **promotion into core** by opening a PR against the ontology repo. The core file is built, not edited: a new component class goes into `core/scaffold_instructions.json`, anything else into `core/bare_core.ttl`, and `tools/build_core.py` rebuilds `core/dici_onto_core.ttl`. Full process, criteria, and service-compatibility contract: [`digicities-ontology/docs/CORE_EVOLUTION.md`](https://github.com/uesl-empa/digicities-ontology/blob/main/docs/CORE_EVOLUTION.md).

## How to cite

If you use the Digicities platform in published work, please cite it:

```bibtex
@software{digicities-platform,
  title   = {Digicities Platform},
  author  = {Allan, James and Fricker, Reto and Akdodov, Khusrav},
  year    = {2026},
  version = {0.5.0},
  url     = {https://github.com/uesl-empa/digicities-platform},
}
```

The same metadata is in [`CITATION.cff`](CITATION.cff) ("Cite this repository" on GitHub). A Zenodo DOI per release will be added once the Zenodo integration is enabled for this repository.

Or in prose: *"… built on the Digicities platform (https://github.com/uesl-empa/digicities-platform)."*

If you also use the ontology, please cite it separately. See [`digicities-ontology`](https://github.com/uesl-empa/digicities-ontology#how-to-cite).

## License

[Apache License 2.0](LICENSE). Copyright © 2026.

The vendored ontology is **CC BY 4.0**. The bundled QUDT unit list is **CC BY 4.0** (Topquadrant / QUDT.org). The default triplestore (Apache Jena Fuseki) is **Apache 2.0**. An optional GraphDB Free overlay is available; note that it is proprietary under Ontotext's EULA, not open source. See [`NOTICE`](NOTICE) and [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

## Funding & acknowledgements

Digicities was funded through the SFOE P+D program under the ERA-Net Smart Energy Systems joint initiative *Digital Transformation for the Energy Transition*, grant agreement No 88397.

The authors thank all Digicities project collaborators and contributors who helped guide the development of the platform and the ontology.

The open-source release of this project (repository split, license audit, CI scaffolding, deployment documentation) was prepared with the assistance of [Claude Code](https://claude.com/claude-code).

Since that release, portions of the codebase have continued to be developed and adapted with AI assistance. Wherever this happens, a `Co-Authored-By` trailer naming the AI model used is added to the commit, and contributors are expected to follow the same convention — in the interest of full transparency about how the code was produced.
