# SPDX-License-Identifier: Apache-2.0
"""In-memory workspace registry cache + background refresh.

The filesystem/YAML/NextCloud discovery (``backend.workspace.load_registry``) is
expensive and was run on EVERY request via ``deps.get_ctx``. Here it runs on a timer
in a background thread; requests read this cache (a dict lookup), and each refresh
also mirrors the catalog into the metadata DB (best-effort). This is the phase-1
perf win with no behavioural change — every workspace stays visible.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from backend.workspace import load_registry

_lock = threading.Lock()
_by_id: dict = {}
_contexts: list = []
_loaded = False


def _sync_db(contexts) -> None:
    try:
        from backend.db.workspaces_repo import upsert
        from backend.workspace.registry import BUNDLED_DEMO_IDS
        for c in contexts:
            upsert({
                "id": c.id, "name": c.name,
                "backend": getattr(getattr(c, "storage", None), "protocol", "local"),
                "graphdb_repo": c.graphdb_repository or c.id,
                "description": c.description or "",
                "tags": list(getattr(c, "tags", []) or []),
                "protected": c.id in BUNDLED_DEMO_IDS,
            })
    except Exception:
        pass                                    # DB is optional — never block a refresh


def refresh() -> None:
    """Re-scan discovery into the cache and mirror the catalog into the DB."""
    global _by_id, _contexts, _loaded
    contexts = list(load_registry())
    with _lock:
        _contexts = contexts
        _by_id = {c.id: c for c in contexts}
        _loaded = True
    _sync_db(contexts)


def _ensure_loaded() -> None:
    with _lock:
        loaded = _loaded
    if not loaded:
        refresh()


def by_id(ws_id: str):
    """The WorkspaceContext for ``ws_id`` from the cache, else a direct registry lookup
    (covers a just-created workspace before the next refresh). None if unknown."""
    _ensure_loaded()
    with _lock:
        ctx = _by_id.get(ws_id)
    if ctx is None:
        ctx = load_registry().by_id(ws_id)      # fallback: never miss a real workspace
    return ctx


def all_contexts() -> list:
    _ensure_loaded()
    with _lock:
        return list(_contexts)


def start_background(interval: Optional[float] = None) -> None:
    """Start the periodic refresh thread. Safe to call once at startup."""
    period = interval if interval is not None else float(os.getenv("WORKSPACE_REFRESH_SECONDS", "30"))

    def _loop():
        try:
            from backend.db.workspaces_repo import init_db
            init_db()
        except Exception:
            pass
        while True:
            try:
                refresh()
            except Exception:
                pass
            time.sleep(period)

    threading.Thread(target=_loop, name="workspace-registry-refresh", daemon=True).start()
