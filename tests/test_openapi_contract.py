# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The REST surface is a published contract, not an implementation detail.

`apps/api/openapi.json` is the frozen v1 snapshot handed to the React frontend
(digicities-frontend). This gate fails when a route or verb appears, changes,
or disappears without the snapshot being regenerated on purpose:

    python -c "import json; from apps.api.main import app; \\
        json.dump(app.openapi(), open('apps/api/openapi.json','w',encoding='utf-8',newline='\\n'), \\
        indent=2, sort_keys=True, ensure_ascii=False)"

Only paths + verbs are compared exactly — schema bodies vary with FastAPI's
generator version and get reviewed as ordinary snapshot diffs instead.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

SNAPSHOT = Path(__file__).resolve().parent.parent / "apps" / "api" / "openapi.json"


def _routes(spec: dict) -> dict[str, list[str]]:
    return {path: sorted(ops) for path, ops in spec["paths"].items()}


def test_api_surface_matches_committed_snapshot():
    from apps.api.main import app

    live = _routes(app.openapi())
    frozen = _routes(json.loads(SNAPSHOT.read_text(encoding="utf-8")))

    missing = {p: v for p, v in frozen.items() if live.get(p) != v}
    added = {p: v for p, v in live.items() if p not in frozen}
    assert not missing and not added, (
        "REST surface drifted from apps/api/openapi.json.\n"
        f"  changed/removed: {sorted(missing)}\n"
        f"  added: {sorted(added)}\n"
        "  If intentional, regenerate the snapshot (see module docstring) and "
        "commit it so the frontend sees the change."
    )
