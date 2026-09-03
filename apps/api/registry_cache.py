# SPDX-License-Identifier: Apache-2.0
"""In-memory workspace registry cache + background refresh.

The filesystem/YAML/NextCloud discovery (``backend.workspace.load_registry``) is
expensive and was run on EVERY request via ``deps.get_ctx``. Here it runs on a timer
in a background thread; requests read this cache (a dict lookup), and each refresh
also mirrors the catalog into the metadata DB (best-effort). This is the phase-1
perf win with no behavioural change — every workspace stays visible.

Phase 2: ``GET /api/workspaces`` used to compute each workspace's summary (a
``workspace_meta`` read + a full ``os.walk`` of the workspace tree for its
"last updated" stamp) on EVERY request, for EVERY workspace — cheap at a handful
of workspaces, but O(total files across all workspaces) per page load once there
are dozens, and a real network round-trip per workspace on non-local storage
(NextCloud). Compute it here instead, in the same background refresh.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from backend.workspace import load_registry, read_workspace_metadata, workspace_last_updated

_lock = threading.Lock()
_by_id: dict = {}
_contexts: list = []
_summaries: dict = {}
_loaded = False


def _compute_summary(ctx) -> dict:
    from .deps import ws_root
    root = ws_root(ctx)
    meta = read_workspace_metadata(ctx)
    return {
        "updated_at": workspace_last_updated(root) if root.exists() else None,
        "created_date": str(meta.get("created") or meta.get("created_date") or ""),
    }


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
    global _by_id, _contexts, _summaries, _loaded
    contexts = list(load_registry())
    # Keyed by object identity, not ws id: a request-time context that ISN'T one of
    # these exact instances (a just-created workspace, or a caller that resolves its
    # own ctx — e.g. tests exercising a fake/temp one under a real id) is by definition
    # not something this refresh computed, so summary_for must recompute it fresh
    # rather than serve another workspace's stale value for the same id.
    summaries = {id(c): _compute_summary(c) for c in contexts}
    with _lock:
        _contexts = contexts
        _by_id = {c.id: c for c in contexts}
        _summaries = summaries
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


def summary_for(ctx) -> dict:
    """Cached ``{updated_at, created_date}`` for this exact context object — no disk/network
    I/O when it's one of the instances the last ``refresh()`` computed. A context that isn't
    (not yet refreshed, or a caller-supplied one) is computed fresh on the spot — correct
    over fast, since it's off the hot path (only ever one uncached workspace, not all of
    them)."""
    _ensure_loaded()
    with _lock:
        s = _summaries.get(id(ctx))
    return s if s is not None else _compute_summary(ctx)


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
