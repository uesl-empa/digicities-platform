# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Triplestore abstraction.

Two SPARQL-protocol-compatible backends are supported:

- **Fuseki** (Apache Jena Fuseki, Apache-2.0) — the v0.3 default.
- **GraphDB** (Ontotext GraphDB Free, proprietary EULA) — opt-in via
  docker-compose.graphdb.yml.

Switch backends with $TRIPLESTORE_BACKEND (`fuseki` or `graphdb`). Each
backend implements the same minimal API needed for workspace provisioning:

- `dataset_exists(name)`         — does the repo/dataset exist?
- `create_dataset(name, label)`  — create a new persistent repo/dataset
- `dataset_url(name)`            — URL fragment to use for SPARQL endpoints
                                   (`/repositories/<n>` vs `/<n>`)
- `graph_store_url(name, graph)` — full URL for Graph Store HTTP Protocol
                                   uploads to a specific named graph
"""

from .factory import get_backend, get_backend_name

__all__ = ["get_backend", "get_backend_name"]
