# Third-party licenses

The Digicities platform is licensed under [Apache License 2.0](LICENSE). The components below are bundled with this repository or pulled at runtime; their own licenses apply to those files.

This file is informational. See [NOTICE](NOTICE) for the authoritative attribution required by Apache 2.0 §4(d).

## Python dependencies (installed via `requirements.txt`)

All permissive (Apache 2.0, MIT, or BSD). All compatible with Apache 2.0.

| Package | License | Project URL |
|---|---|---|
| streamlit | Apache-2.0 | https://github.com/streamlit/streamlit |
| pandas | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| numpy | BSD-3-Clause | https://github.com/numpy/numpy |
| openpyxl | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| requests | Apache-2.0 | https://github.com/psf/requests |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| rdflib | BSD-3-Clause | https://github.com/RDFLib/rdflib |
| matplotlib | Matplotlib License (BSD-style) | https://github.com/matplotlib/matplotlib |
| plotly | MIT | https://github.com/plotly/plotly.py |
| folium | MIT | https://github.com/python-visualization/folium |
| streamlit-folium | MIT | https://github.com/randyzwitch/streamlit-folium |
| filetype | MIT | https://github.com/h2non/filetype.py |
| pyyaml | MIT | https://github.com/yaml/pyyaml |
| ipywidgets | BSD-3-Clause | https://github.com/jupyter-widgets/ipywidgets |

Full per-package license texts are available in the wheels installed into your environment; on a typical install, `pip show <package>` prints the license summary.

## Bundled data and assets

| Path | Source | License |
|---|---|---|
| `services/graphdb/ontology/dici_onto_core.ttl`, `data/ontology/dici_onto_core.ttl` | [Digicities ontology](https://github.com/uesl-empa/digicities-ontology) (vendored) | CC BY 4.0 |
| `services/graphdb/ontology/qudt_units.txt`, `data/ontology/imports/qudt_units.txt` | [QUDT](https://www.qudt.org/) (Topquadrant) | CC BY 4.0 |
| `data/logo/eranet logo.png` | [ERA-Net programme](https://www.era-learn.eu/) | Trademark — used as funder attribution |
| `data/logo/icon.png`, `logo with tag.png`, `navigation_logo.png` | Digicities project | Apache-2.0 (with project) |
| `tutorial/sample_data/alpine_village.ttl` and Excel templates | Digicities project | Apache-2.0 (with project) |
| `data/ingestion_template/*` | Digicities project | Apache-2.0 (with project) |

## Container images (pulled at runtime, not redistributed)

| Image | License | Notes |
|---|---|---|
| `stain/jena-fuseki:4.10.0` | [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) | **Default triplestore as of v0.3.** Fully OSI-approved. |
| `ontotext/graphdb:10.7.3` | [Ontotext GraphDB Free EULA](https://www.ontotext.com/products/graphdb/license/) (proprietary, gratis) | **Opt-in overlay (`docker-compose.graphdb.yml`)**. Not open source. Users accept the EULA on first run of the container. |
| `nextcloud:29-apache` | AGPLv3 | Affects re-distributors of NextCloud itself; running the container as part of a stack is fine. |
| `python:3.11-slim` | PSF License (BSD-style) + Debian package mix | Standard Python base image. |
| `curlimages/curl:latest` | curl license (MIT/X derivate) | Used in the init sidecars. |

## Choosing a triplestore

The default stack (Apache Jena Fuseki) gives you a 100% OSI-approved stack — appropriate for strict procurement rules, public-sector deployments, and anyone who wants an unencumbered backend.

Switch to **Ontotext GraphDB Free** via the opt-in overlay (`docker-compose.graphdb.yml` + `TRIPLESTORE_BACKEND=graphdb` in `.env`) if you want:

- The GraphDB Workbench UI for ad-hoc admin
- Built-in inference (RDFS / OWL profiles)
- Sesame-style features that Streamlit panels lean on for richer interactions

The backend abstraction in `backend/triplestore/` handles per-server URL differences automatically; switching is a config change, not a code change.
