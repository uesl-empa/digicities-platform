# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Factory: pick the active triplestore backend based on $TRIPLESTORE_BACKEND.

Default is `fuseki` (Apache-2.0, OSI-approved). Override to `graphdb` to use
Ontotext GraphDB Free via the opt-in docker-compose.graphdb.yml overlay.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .fuseki import FusekiBackend
from .graphdb import GraphDBBackend


def get_backend_name() -> str:
    """Resolved backend name (`fuseki` or `graphdb`). v0.3 default: `fuseki`."""
    return os.environ.get("TRIPLESTORE_BACKEND", "fuseki").strip().lower()


@lru_cache(maxsize=1)
def get_backend():
    """Return a singleton instance of the configured backend."""
    name = get_backend_name()
    if name == "fuseki":
        return FusekiBackend()
    if name == "graphdb":
        return GraphDBBackend()
    raise ValueError(
        f"Unknown TRIPLESTORE_BACKEND={name!r}. Set to 'fuseki' (default) or 'graphdb'."
    )
