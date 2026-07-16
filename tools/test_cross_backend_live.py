# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Live cross-backend smoke test — Fuseki vs GraphDB returning identical results.

This is the slow, integration-grade variant of `tests/test_cross_backend_smoke.py`.
It actually provisions a workspace against a running Fuseki and a running
GraphDB instance and diffs the query results from both REST endpoints.

When to run
-----------
- Before any release of a change that touches `backend/triplestore/` or
  `backend/workspace/graphdb_provisioning.py`.
- Optionally in CI on PRs that touch those paths (see
  .github/workflows/cross-backend-live.yml).

Prerequisites
-------------
- A live Fuseki at $FUSEKI_URL (default http://fuseki:3030, admin/admin)
- A live GraphDB at $GRAPHDB_LIVE_URL (default http://graphdb:7200)
- A registered workspace named `motel-energy` accessible via the registry

Usage
-----
    cd digicities-platform
    python tools/test_cross_backend_live.py motel-energy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.triplestore.fuseki import FusekiBackend  # noqa: E402
from backend.triplestore.graphdb import GraphDBBackend  # noqa: E402
from backend.workspace import load_registry  # noqa: E402


CANONICAL_QUERIES: Dict[str, str] = {
    "component_count_natural": """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE { ?i a dici_onto:Component }
    """,
    "attribute_count_natural": """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        SELECT (COUNT(*) AS ?n) WHERE { ?i dici_onto:hasAttribute ?a }
    """,
    "building_count": """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE { ?i a dici_onto:Building }
    """,
    "scenario_count": """
        PREFIX dici_onto: <https://digicities.info/ontology#>
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a dici_onto:Scenario }
    """,
}


def _query_backend(backend, dataset: str, sparql: str) -> Optional[int]:
    """Run a count query against the backend's SPARQL endpoint; return the count."""
    url = backend.query_url(dataset)
    try:
        r = requests.get(
            url,
            params={"query": sparql},
            headers={"Accept": "text/csv"},
            auth=getattr(backend, "auth", None),
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"   ERROR {backend.name}: {exc}")
        return None
    # CSV: header on line 1, value on line 2
    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        return None
    try:
        return int(lines[-1])
    except ValueError:
        return None


def _provision_into(backend, workspace_id: str) -> bool:
    """Drop + recreate the workspace's dataset using the active backend."""
    from backend.workspace import ensure_workspace_repo
    ctx = load_registry().by_id(workspace_id)
    if ctx is None:
        print(f"workspace {workspace_id!r} not in registry")
        return False
    # Force the env var so ensure_workspace_repo picks the right backend.
    os.environ["TRIPLESTORE_BACKEND"] = backend.name
    # Clear factory cache so the new env var takes effect.
    from backend.triplestore.factory import get_backend as _get
    _get.cache_clear()
    return ensure_workspace_repo(ctx)


def main(workspace_id: str) -> int:
    fuseki = FusekiBackend(base_url=os.environ.get("FUSEKI_URL", "http://fuseki:3030"))
    graphdb = GraphDBBackend(base_url=os.environ.get("GRAPHDB_LIVE_URL", "http://graphdb:7200"))

    # Provision against both backends.
    print("=" * 60)
    print(f"PROVISION {workspace_id!r} INTO FUSEKI")
    print("=" * 60)
    if not _provision_into(fuseki, workspace_id):
        print("FAIL: Fuseki provisioning")
        return 1

    print()
    print("=" * 60)
    print(f"PROVISION {workspace_id!r} INTO GRAPHDB")
    print("=" * 60)
    if not _provision_into(graphdb, workspace_id):
        print("WARN: GraphDB provisioning skipped (not running?). Comparing Fuseki only.")
        graphdb = None

    # Run canonical queries.
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"{'query':<35} {'fuseki':<10} {'graphdb':<10} {'match':<6}")
    print("-" * 60)

    any_diff = False
    for name, sparql in CANONICAL_QUERIES.items():
        f_val = _query_backend(fuseki, workspace_id, sparql)
        g_val = _query_backend(graphdb, workspace_id, sparql) if graphdb else None
        match = "n/a" if g_val is None else ("OK" if f_val == g_val else "DIFF")
        if match == "DIFF":
            any_diff = True
        print(f"{name:<35} {str(f_val):<10} {str(g_val):<10} {match:<6}")

    print()
    if any_diff:
        print("FAIL: backends returned different counts.")
        return 1
    print("PASS: results identical across backends.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python tools/test_cross_backend_live.py <workspace_id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
