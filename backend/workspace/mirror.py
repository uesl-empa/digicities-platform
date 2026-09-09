# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Local↔remote workspace mirror (phase 2 of the NextCloud-default-storage plan).

The cloud deployment's contract: the server keeps a LOCAL working copy of each
workspace under ``$USECASES_DIR/<id>`` — the converter, the onboarding agent
and every ``ws_root`` caller keep operating on real files exactly as on Docker
Desktop — while the workspace's ``ctx.storage`` (NextCloud over WebDAV) is the
durable, user-visible store. This module syncs the two:

- :func:`pull` — refresh the local copy from remote. Called from ``get_ctx``
  on every request, throttled (``MIRROR_PULL_SECONDS``, default 30) so it
  costs one WebDAV listing at most every N seconds per workspace. Downloads
  new/changed remote files; NEVER deletes local files (a local write that
  hasn't been pushed yet must survive a pull).
- :func:`push` — publish local state to remote. Called after write
  boundaries (mutating API requests, agent turns, workspace lifecycle).
  Uploads new/changed files and propagates local deletions of files THIS
  mirror previously pushed or pulled (so ``reset workspace`` empties the
  remote too, but a file created directly in NextCloud is never deleted by
  a push that simply hasn't seen it).

Change detection is manifest-based: ``.mirror-manifest.json`` in the local
root records (size, local mtime, remote size) per file as of the last sync.
Local mtimes are authoritative for "did WE change it"; remote size changes
signal "did THEY change it" — WebDAV mtimes are too inconsistent to trust.

v1 concurrency model (per the approved plan): one api instance per
deployment, last-writer-wins. Conflicting edits (local build vs. NextCloud
web edit between syncs) resolve in favor of whichever side syncs last.

Everything is fail-soft: a mirror error logs and returns — the request that
triggered it must never 500 because NextCloud hiccuped. And every function is
a no-op for ``protocol == "file"`` workspaces, so local deployments are
byte-for-byte unaffected.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .context import WorkspaceContext

MANIFEST_NAME = ".mirror-manifest.json"
# Local-only names, never mirrored in either direction. Secrets stay server-side.
EXCLUDE_NAMES = {MANIFEST_NAME, ".agent-keys.json", "__pycache__", ".DS_Store"}

_lock = threading.Lock()
_last_pull: dict[str, float] = {}          # workspace id -> monotonic seconds


def _pull_ttl() -> float:
    try:
        return float(os.getenv("MIRROR_PULL_SECONDS", "30"))
    except ValueError:
        return 30.0


def enabled(ctx: WorkspaceContext) -> bool:
    """Mirroring applies only to remote-backed workspaces."""
    storage = getattr(ctx, "storage", None)
    return storage is not None and getattr(storage, "protocol", "file") != "file"


def local_root(ctx: WorkspaceContext) -> Path:
    """The server-local working copy for ``ctx`` — the same path ``ws_root``
    serves, spelled here so backend code needs no apps.api import."""
    return Path(os.getenv("USECASES_DIR", "/app/data/usecases")) / ctx.id


def _excluded(rel: str) -> bool:
    return any(part in EXCLUDE_NAMES for part in rel.split("/"))


def _local_files(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if _excluded(rel):
            continue
        st = p.stat()
        out[rel] = {"size": st.st_size, "mtime": st.st_mtime}
    return out


def _load_manifest(root: Path) -> dict:
    try:
        return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(root: Path, manifest: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")


def pull(ctx: WorkspaceContext, force: bool = False) -> dict:
    """Refresh the local working copy from remote (throttled unless forced).

    Returns ``{"pulled": [...], "skipped": bool}``; empty/no-op results are
    normal. Never raises.
    """
    if not enabled(ctx):
        return {"pulled": [], "skipped": True}
    now = time.monotonic()
    with _lock:
        last = _last_pull.get(ctx.id, 0.0)
        if not force and now - last < _pull_ttl():
            return {"pulled": [], "skipped": True}
        _last_pull[ctx.id] = now
    try:
        return _pull(ctx)
    except Exception as exc:                      # fail-soft, always
        print(f"[mirror] pull({ctx.id}) failed: {type(exc).__name__}: {exc}")
        return {"pulled": [], "skipped": False, "error": str(exc)}


def _pull(ctx: WorkspaceContext) -> dict:
    root = local_root(ctx)
    manifest = _load_manifest(root)
    remote = {rel: info for rel, info in ctx.storage.walk_files().items()
              if not _excluded(rel)}
    local = _local_files(root)
    pulled: list[str] = []
    for rel, rinfo in remote.items():
        entry = manifest.get(rel)
        if rel in local:
            # Unchanged since we last synced it → nothing to do. A remote
            # size change signals an edit made in NextCloud directly.
            if entry and entry.get("remote_size") == rinfo["size"]:
                continue
            if not entry and local[rel]["size"] == rinfo["size"]:
                continue                          # same content, first sighting
        data = ctx.storage.read_bytes(rel)
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        st = target.stat()
        manifest[rel] = {"size": st.st_size, "mtime": st.st_mtime,
                         "remote_size": rinfo["size"]}
        pulled.append(rel)
    # Remote deletions: a file the manifest knows, absent remotely, and
    # UNCHANGED locally since the last sync → mirror the deletion. A local
    # file with unsynced changes survives (push will re-publish it).
    for rel, entry in list(manifest.items()):
        if rel in remote:
            continue
        linfo = local.get(rel)
        if linfo and linfo["size"] == entry.get("size") \
                and abs(linfo["mtime"] - entry.get("mtime", 0)) < 1e-6:
            try:
                (root / rel).unlink()
                pulled.append(f"-{rel}")
            except OSError:
                pass
        manifest.pop(rel, None)
    if pulled:
        _save_manifest(root, manifest)
    return {"pulled": pulled, "skipped": False}


def push(ctx: WorkspaceContext) -> dict:
    """Publish the local working copy to remote. Returns
    ``{"pushed": [...], "deleted": [...]}``. Never raises."""
    if not enabled(ctx):
        return {"pushed": [], "deleted": [], "skipped": True}
    try:
        return _push(ctx)
    except Exception as exc:
        print(f"[mirror] push({ctx.id}) failed: {type(exc).__name__}: {exc}")
        return {"pushed": [], "deleted": [], "error": str(exc)}


def _push(ctx: WorkspaceContext) -> dict:
    root = local_root(ctx)
    manifest = _load_manifest(root)
    local = _local_files(root)
    pushed: list[str] = []
    deleted: list[str] = []
    for rel, linfo in local.items():
        entry = manifest.get(rel)
        if entry and entry.get("size") == linfo["size"] \
                and abs(entry.get("mtime", 0) - linfo["mtime"]) < 1e-6:
            continue                              # unchanged since last sync
        data = (root / rel).read_bytes()
        ctx.storage.write_bytes(rel, data)
        manifest[rel] = {"size": linfo["size"], "mtime": linfo["mtime"],
                         "remote_size": len(data)}
        pushed.append(rel)
    # Deletion propagation: only files THIS mirror has seen (manifest) are
    # deleted remotely — never remote-only files we simply haven't pulled.
    for rel in list(manifest):
        if rel in local:
            continue
        try:
            ctx.storage.delete(rel)
            deleted.append(rel)
        except Exception:
            pass                                   # absent remotely already
        manifest.pop(rel, None)
    if pushed or deleted:
        _save_manifest(root, manifest)
    return {"pushed": pushed, "deleted": deleted}
