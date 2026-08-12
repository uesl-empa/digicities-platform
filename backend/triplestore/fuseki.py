# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Apache Jena Fuseki backend.

Dataset creation uses Fuseki's admin API: POST /$/datasets with form fields
`dbName=<n>` and `dbType=tdb2` (persistent disk-backed) or `mem`. Graph
Store uploads go to /<dataset>/data?graph=...

Reference: https://jena.apache.org/documentation/fuseki2/fuseki-server-protocol.html
"""

from __future__ import annotations

import os
from urllib.parse import quote

import requests


class FusekiBackend:
    name = "fuseki"

    def __init__(self, base_url: str | None = None):
        # Default to the in-cluster Docker hostname. Override with $FUSEKI_URL
        # or $GRAPHDB_URL (the latter is shared with the SPARQL client config).
        self.base_url = (
            base_url
            or os.environ.get("FUSEKI_URL")
            or os.environ.get("GRAPHDB_URL")
            or "http://fuseki:3030"
        ).rstrip("/")
        # Optional admin auth (Fuseki's default unauthenticated; override via env).
        self._auth = None
        user = os.environ.get("FUSEKI_ADMIN_USER")
        pw = os.environ.get("FUSEKI_ADMIN_PASSWORD")
        if user and pw:
            self._auth = (user, pw)

    # ---- API ---------------------------------------------------------------

    def dataset_exists(self, dataset: str) -> bool:
        try:
            r = requests.get(f"{self.base_url}/$/datasets/{dataset}", auth=self._auth, timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def create_dataset(self, dataset: str, label: str = "") -> bool:
        """Create a persistent (TDB2) dataset named `dataset`.

        Idempotent: if the dataset already exists, returns True.
        """
        if self.dataset_exists(dataset):
            return True
        try:
            r = requests.post(
                f"{self.base_url}/$/datasets",
                data={"dbName": dataset, "dbType": "tdb2"},
                auth=self._auth,
                timeout=30,
            )
            if r.status_code in (200, 201):
                return True
            print(f"[triplestore.fuseki] create_dataset({dataset}) HTTP {r.status_code}: {r.text[:200]}")
            return False
        except requests.RequestException as exc:
            print(f"[triplestore.fuseki] create_dataset({dataset}) failed: {exc}")
            return False

    def delete_dataset(self, dataset: str) -> bool:
        """Remove the dataset from the server AND delete its TDB2 files.

        Fuseki historically had two admin calls here: ``DELETE /$/datasets/<n>``
        takes the dataset offline while leaving its files on disk (so recreating
        the same name can resurrect the old data), and ``?state=delete`` removes
        the database itself. Newer builds fold both into the plain DELETE, so try
        the explicit form first and fall back.
        """
        if not self.dataset_exists(dataset):
            return True                       # already gone
        for url in (f"{self.base_url}/$/datasets/{dataset}?state=delete",
                    f"{self.base_url}/$/datasets/{dataset}"):
            try:
                r = requests.delete(url, auth=self._auth, timeout=30)
                if r.status_code not in (200, 204, 404):
                    print(f"[triplestore.fuseki] delete_dataset({dataset}) HTTP "
                          f"{r.status_code}: {r.text[:200]}")
                    continue
                if not self.dataset_exists(dataset):
                    return True
            except requests.RequestException as exc:
                print(f"[triplestore.fuseki] delete_dataset({dataset}) failed: {exc}")
                return False
        return not self.dataset_exists(dataset)

    def dataset_path(self, dataset: str) -> str:
        return f"/{dataset}"

    def graph_store_url(self, dataset: str, graph_iri: str | None) -> str:
        # Standard SPARQL Graph Store HTTP Protocol endpoint.
        # graph_iri=None → default graph (Fuseki uses ?default).
        if not graph_iri:
            return f"{self.base_url}/{dataset}/data?default"
        return f"{self.base_url}/{dataset}/data?graph={quote(graph_iri, safe='')}"

    def query_url(self, dataset: str) -> str:
        return f"{self.base_url}/{dataset}/query"

    def update_url(self, dataset: str) -> str:
        return f"{self.base_url}/{dataset}/update"

    @property
    def auth(self):
        """Auth tuple for write operations; None if Fuseki runs unauthenticated."""
        return self._auth
