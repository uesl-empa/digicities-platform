# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Ontotext GraphDB backend.

Repository creation uses GraphDB's REST API: POST /rest/repositories with a
multipart-form config TTL. Graph Store uploads go to
/repositories/<repo>/rdf-graphs/service?graph=...
"""

from __future__ import annotations

import os
from urllib.parse import quote

import requests


REPO_CONFIG_TEMPLATE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rep: <http://www.openrdf.org/config/repository#> .
@prefix sr: <http://www.openrdf.org/config/repository/sail#> .
@prefix sail: <http://www.openrdf.org/config/sail#> .
@prefix owlim: <http://www.ontotext.com/trree/owlim#> .

[] a rep:Repository ;
   rep:repositoryID "{repo_id}" ;
   rdfs:label "{label}" ;
   rep:repositoryImpl [
      rep:repositoryType "graphdb:SailRepository" ;
      sr:sailImpl [
         sail:sailType "graphdb:Sail" ;
         owlim:ruleset "empty" ;
         owlim:storage-folder "storage" ;
         owlim:enable-context-index "true" ;
         owlim:enablePredicateList "true" ;
         owlim:in-memory-literal-properties "true" ;
         owlim:enable-literal-index "true" ;
         owlim:disable-sameAs "true"
      ]
   ] .
"""


class GraphDBBackend:
    name = "graphdb"

    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url
            or os.environ.get("GRAPHDB_REST_URL")
            or os.environ.get("GRAPHDB_URL")
            or "http://graphdb:7200"
        ).rstrip("/")

    def dataset_exists(self, dataset: str) -> bool:
        try:
            r = requests.head(f"{self.base_url}/rest/repositories/{dataset}", timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def create_dataset(self, dataset: str, label: str = "") -> bool:
        config_ttl = REPO_CONFIG_TEMPLATE.format(repo_id=dataset, label=label or f"Workspace: {dataset}")
        try:
            r = requests.post(
                f"{self.base_url}/rest/repositories",
                files={"config": ("repo-config.ttl", config_ttl, "text/turtle")},
                timeout=30,
            )
            return r.status_code in (201, 200)
        except requests.RequestException as exc:
            print(f"[triplestore.graphdb] create_dataset({dataset}) failed: {exc}")
            return False

    def delete_dataset(self, dataset: str) -> bool:
        """Drop the repository and its data via the GraphDB REST API."""
        if not self.dataset_exists(dataset):
            return True                       # already gone
        try:
            r = requests.delete(f"{self.base_url}/rest/repositories/{dataset}", timeout=30)
            if r.status_code in (200, 204, 404):
                return True
            print(f"[triplestore.graphdb] delete_dataset({dataset}) HTTP "
                  f"{r.status_code}: {r.text[:200]}")
            return False
        except requests.RequestException as exc:
            print(f"[triplestore.graphdb] delete_dataset({dataset}) failed: {exc}")
            return False

    def dataset_path(self, dataset: str) -> str:
        return f"/repositories/{dataset}"

    def graph_store_url(self, dataset: str, graph_iri: str | None) -> str:
        # GraphDB uses Sesame's named-graph endpoint.
        # graph_iri=None → default graph (statements endpoint, no context).
        if not graph_iri:
            return f"{self.base_url}/repositories/{dataset}/statements"
        return f"{self.base_url}/repositories/{dataset}/rdf-graphs/service?graph={quote(graph_iri, safe='')}"

    def query_url(self, dataset: str) -> str:
        """URL accepting SPARQL queries via `?query=...`."""
        return f"{self.base_url}/repositories/{dataset}"

    def update_url(self, dataset: str) -> str:
        """URL accepting SPARQL updates via `?update=...` or POST body."""
        return f"{self.base_url}/repositories/{dataset}/statements"

    @property
    def auth(self):
        """GraphDB Free typically runs unauthenticated in dev setups."""
        return None
