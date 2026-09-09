# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Storage-parity gate (phase 0 of the NextCloud-default-storage plan).

The cloud deployment keeps a LOCAL working copy of each workspace on the
server and mirrors it to NextCloud at defined read/write boundaries
(``backend/workspace/mirror.py``, phase 2). That only works if workspace
paths are derived in a small, known set of places — every module that invents
its own path from ``USECASES_DIR`` or calls ``ws_root`` directly is a place
the mirror layer must wrap, and a NEW one added casually is a silent hole in
the cloud deployment.

So this gate FREEZES the current inventory. It does not fail today's code —
all existing functionality is exactly as it was — it fails the build when a
new file starts deriving workspace paths outside the sanctioned seams, forcing
the author to either route through the storage/mirror layer or consciously
extend the allowlist here (and thereby the phase-2 work list).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── inventory as of 2026-09-09 (phase-0 audit) ────────────────────────────────
# apps/api modules calling ws_root() — each is a pull/push boundary for the
# mirror layer. Anything new must go through the mirror instead.
WS_ROOT_CALLERS = {
    "apps/api/agent.py",
    "apps/api/data_products.py",
    "apps/api/deps.py",            # the definition itself
    "apps/api/files.py",
    "apps/api/main.py",
    "apps/api/registry_cache.py",
    "apps/api/replica.py",
    "apps/api/scenario.py",
    "apps/api/service.py",
    "apps/api/submission.py",
}

# Files allowed to read USECASES_DIR / the literal default usecases path.
# These ARE the storage seams (workspace paths module, registry, creation,
# seeding) plus two legacy local-mode fallbacks.
USECASES_DERIVERS = {
    "apps/api/deps.py",
    "backend/workspace/mirror.py",   # local_root: THE sanctioned mirror seam
    "backend/workspace/paths.py",
    "backend/workspace/creation.py",
    "backend/workspace/registry.py",
    "backend/workspace/seed.py",
    "backend/ontology_manager/functions/base.py",
    "backend/replica_builder/cli.py",
}

_SCAN_DIRS = ("apps/api", "backend")


def _source_files():
    for d in _SCAN_DIRS:
        for p in (REPO_ROOT / d).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            yield p


def _rel(p: Path) -> str:
    return p.relative_to(REPO_ROOT).as_posix()


def test_ws_root_callers_are_frozen():
    pattern = re.compile(r"\bws_root\s*\(")
    found = {_rel(p) for p in _source_files()
             if pattern.search(p.read_text(encoding="utf-8", errors="ignore"))}
    new = found - WS_ROOT_CALLERS
    gone = WS_ROOT_CALLERS - found
    assert not new, (
        f"NEW ws_root caller(s): {sorted(new)}. Workspace paths must flow "
        "through the storage/mirror seam (see the NextCloud-default-storage "
        "plan) — do not derive them ad hoc. If this is a deliberate new "
        "boundary, add it to WS_ROOT_CALLERS *and* to the mirror work list.")
    assert not gone, (
        f"{sorted(gone)} no longer call ws_root — great; shrink the allowlist "
        "so the gate stays tight.")


def test_usecases_dir_derivations_are_frozen():
    pattern = re.compile(r"USECASES_DIR|/app/data/usecases")
    found = {_rel(p) for p in _source_files()
             if pattern.search(p.read_text(encoding="utf-8", errors="ignore"))}
    new = found - USECASES_DERIVERS
    gone = USECASES_DERIVERS - found
    assert not new, (
        f"NEW USECASES_DIR derivation(s): {sorted(new)}. The local workspace "
        "root is spelled out in the storage seams only — import from "
        "backend.workspace.paths / apps.api.deps instead. If deliberate, "
        "extend USECASES_DERIVERS and the mirror work list.")
    assert not gone, (
        f"{sorted(gone)} no longer touch USECASES_DIR — shrink the allowlist.")
