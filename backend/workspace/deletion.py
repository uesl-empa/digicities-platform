# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Empty or remove a workspace.

Two operations, deliberately distinct:

* ``clear_workspace(ctx)`` — the workspace survives but its *contents* go: every
  authored file under the canonical content folders, and every triple in its
  triplestore dataset. The folder layout, ``workspace_meta/metadata.json`` and the
  dataset itself are kept, and the core ontology is reloaded, so the workspace is
  immediately reusable — exactly the state a freshly created workspace is in.

* ``delete_workspace(ws_id)`` — the workspace goes: its storage tree, its
  triplestore dataset, and its ``workspaces.yaml`` entry if it has one.

Both are destructive and irreversible; the caller is responsible for confirming
with the user first. Both refuse to touch a bundled demo workspace, because those
ship with the repo and deleting one would modify the checkout rather than user data.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import yaml

from .context import WorkspaceContext
from .graphdb_provisioning import clear_all_graphs, delete_repository, ensure_workspace_repo
from .registry import (
    BUNDLED_DEMO_IDS,
    DEFAULT_REGISTRY,
    _registry_path,
    load_registry,
)
from .storage import CANONICAL_SUBDIRS, WORKSPACE_META

# Everything except workspace_meta: the metadata.json is the workspace's identity
# (name, description, tags drive the landing-page card), so clearing contents must
# not remove it or the workspace would vanish from discovery.
_CONTENT_SUBDIRS = [d for d in CANONICAL_SUBDIRS if d != WORKSPACE_META]


class WorkspaceProtected(Exception):
    """Raised when the target is a bundled demo workspace, which must not be touched."""


def _guard(ws_id: str) -> None:
    if ws_id in set(BUNDLED_DEMO_IDS):
        raise WorkspaceProtected(
            f"'{ws_id}' is a bundled demo workspace that ships with the platform — "
            "it can't be cleared or deleted. Copy it to a new workspace instead."
        )


def clear_workspace(ctx: WorkspaceContext, *, reload_core: bool = True) -> dict:
    """Delete every authored file and every triple, keeping the workspace itself.

    Returns a summary: ``{"files_deleted": int, "graphs_cleared": bool,
    "core_reloaded": bool}``.
    """
    _guard(ctx.id)
    storage = ctx.storage

    deleted = 0
    for sub in _CONTENT_SUBDIRS:
        try:
            entries = storage.glob(f"{sub}/**")
        except Exception:
            continue
        # Deepest first so a directory is emptied before we try to remove it, and
        # never remove the canonical folder itself — the layout has to survive.
        for rel in sorted(entries, key=lambda p: p.count("/"), reverse=True):
            rel = rel.rstrip("/")
            if not rel or rel == sub or rel.endswith("/.gitkeep"):
                continue
            try:
                storage.delete(rel)
                deleted += 1
            except Exception:
                pass                       # a stray unreadable file must not abort the clear

    # Put the canonical layout back in case a directory went with its contents.
    try:
        storage.ensure_canonical_layout()
    except Exception:
        pass

    cleared = clear_all_graphs(ctx.graphdb_repository or ctx.id)
    reloaded = False
    if reload_core and cleared:
        # ensure_workspace_repo re-reads the (now empty) folders, so this restores
        # the core ontology and leaves the instance/scenario graphs empty.
        try:
            reloaded = bool(ensure_workspace_repo(ctx))
        except Exception as exc:
            print(f"[workspace.clear] core reload failed for {ctx.id}: {exc}")

    return {"files_deleted": deleted, "graphs_cleared": cleared, "core_reloaded": reloaded}


def delete_workspace(
    ws_id: str,
    *,
    drop_dataset: bool = True,
    ctx: Optional[WorkspaceContext] = None,
) -> dict:
    """Remove a workspace entirely: files, triplestore dataset, registry entry.

    ``drop_dataset=False`` keeps the triplestore dataset (useful when the same
    dataset is shared, or when you want the data to outlive the folder).

    Returns a summary: ``{"files_removed": bool, "dataset_dropped": bool,
    "registry_entry_removed": bool}``.
    """
    _guard(ws_id)

    if ctx is None:
        ctx = load_registry().by_id(ws_id)
    if ctx is None:
        raise ValueError(f"No workspace named '{ws_id}'.")

    files_removed = _remove_storage_tree(ctx)

    dataset_dropped = False
    if drop_dataset:
        dataset_dropped = delete_repository(ctx.graphdb_repository or ws_id)

    registry_removed = _remove_from_yaml(ws_id)

    # A NextCloud workspace is discovered live from the server, so the cached
    # listing has to be dropped or the deleted workspace reappears until restart.
    try:
        from .registry import clear_nextcloud_discovery_cache
        clear_nextcloud_discovery_cache()
    except Exception:
        pass

    return {
        "files_removed": files_removed,
        "dataset_dropped": dataset_dropped,
        "registry_entry_removed": registry_removed,
    }


def _remove_storage_tree(ctx: WorkspaceContext) -> bool:
    """Delete the workspace's whole folder. Local uses shutil (fast, handles
    non-empty trees); other backends fall back to the fsspec recursive remove."""
    storage = ctx.storage
    try:
        if getattr(storage, "protocol", "") == "file":
            root = Path(storage.root)
            if root.exists():
                shutil.rmtree(root)
            return True
        storage.fs.rm(storage.root, recursive=True)
        return True
    except Exception as exc:
        print(f"[workspace.delete] removing storage for {ctx.id} failed: {exc}")
        return False


def _remove_from_yaml(ws_id: str) -> bool:
    """Drop the workspace's entry from workspaces.yaml. Local workspaces are
    auto-discovered from the folder and usually have no entry, so a miss is
    normal and not an error."""
    path = _registry_path() or DEFAULT_REGISTRY
    if not path.exists():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    entries = list(data.get("workspaces") or [])
    kept = [e for e in entries if (e or {}).get("id") != ws_id]
    if len(kept) == len(entries):
        return False
    data["workspaces"] = kept
    try:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return True
    except Exception as exc:
        print(f"[workspace.delete] updating {path} failed: {exc}")
        return False


def workspace_last_updated(root) -> "float | None":
    """Newest file modification time (epoch seconds) anywhere in a workspace
    tree, or None when unreadable/empty.

    The honest "last worked on" signal: every route that touches a workspace —
    Replica Builder, Ontology Manager, the onboarding agent, scenario/service
    writes — lands in a file under the root. Hidden folders are skipped and the
    walk is capped so a pathological tree can't stall the landing page."""
    import os
    latest = None
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            seen += 1
            if seen > 20000:
                return latest
            try:
                m = os.path.getmtime(os.path.join(dirpath, name))
            except OSError:
                continue
            if latest is None or m > latest:
                latest = m
    return latest
