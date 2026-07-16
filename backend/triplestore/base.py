# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Triplestore backend protocol.

A backend wraps the REST/admin surface of a SPARQL server. The SPARQL query/update
itself is standard (handled by GraphDBClient or any other SPARQL HTTP client) — what
differs between Fuseki and GraphDB is dataset/repo creation, listing, and the URL
shape for the Graph Store HTTP Protocol.
"""

from __future__ import annotations

from typing import Protocol


class TriplestoreBackend(Protocol):
    """Minimal triplestore admin surface."""

    name: str
    base_url: str

    def dataset_exists(self, dataset: str) -> bool:
        """True if a dataset (Fuseki) / repository (GraphDB) named `dataset` exists."""
        ...

    def create_dataset(self, dataset: str, label: str = "") -> bool:
        """Create a persistent dataset. Returns True on success, False on failure."""
        ...

    def dataset_path(self, dataset: str) -> str:
        """URL fragment for SPARQL endpoints.

        - GraphDB: `/repositories/<n>`
        - Fuseki:  `/<n>`
        """
        ...

    def graph_store_url(self, dataset: str, graph_iri: str) -> str:
        """Absolute URL for SPARQL Graph Store HTTP Protocol on a named graph."""
        ...
