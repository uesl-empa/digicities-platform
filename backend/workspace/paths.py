# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Container-to-host path translation for local workspaces.

The app usually runs in Docker, where the workspace root is a bind mount
(``${USECASES_HOST_PATH}:/app/data/usecases``). A container path like
``/app/data/usecases/foo`` is meaningless on the user's machine, so these
helpers resolve a workspace's on-disk location and translate it to the host
path the user can actually open.

Headless: no Streamlit. The Streamlit shell (``components.workspace_selector``)
adds the session-state shortcut (the live ``workspace_context``) on top of
``resolve_workspace_local_path``.
"""
from __future__ import annotations

import os
from typing import Optional


def native_local_path(ctx) -> Optional[str]:
    """Native OS path for a local (file-backed) WorkspaceContext, else None."""
    try:
        if ctx is None or getattr(ctx.storage, "protocol", None) != "file":
            return None
        return os.path.normpath(ctx.storage.root)
    except Exception:
        return None


def candidate_local_roots() -> list[str]:
    """Directories a local workspace folder might live under, most-specific first."""
    roots = []
    env_dir = os.environ.get("USECASES_DIR")
    if env_dir:
        roots.append(env_dir)
    try:
        from .registry import DEFAULT_USECASES_DIR, BUNDLED_DEMO_DIR
        roots.append(str(DEFAULT_USECASES_DIR))
        roots.append(str(BUNDLED_DEMO_DIR))
    except Exception:
        pass
    # De-dup while preserving order.
    seen, out = set(), []
    for r in roots:
        key = os.path.normpath(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def to_host_display_path(path: str) -> Optional[str]:
    """Translate a container path under USECASES_DIR to its host path.

    A path like ``/app/data/usecases/foo`` is swapped from the container root
    (USECASES_DIR) to the host root (USECASES_HOST_PATH). Returns None when
    either env var is missing or ``path`` isn't under the mount (e.g. when
    running outside Docker, where the path is already a real host path).
    """
    host_root = os.environ.get("USECASES_HOST_PATH")
    ws_dir = os.environ.get("USECASES_DIR")
    if not host_root or not ws_dir:
        return None
    p = str(path).replace("\\", "/").rstrip("/")
    wd = ws_dir.replace("\\", "/").rstrip("/")
    if p != wd and not p.startswith(wd + "/"):
        return None
    rel = p[len(wd):].lstrip("/")
    host_root = host_root.rstrip("/\\")
    # A Windows host root ("C:/...") is rendered with backslashes so it pastes
    # straight into File Explorer; POSIX roots keep forward slashes.
    if len(host_root) >= 2 and host_root[1] == ":":
        base = host_root.replace("/", "\\")
        return base + ("\\" + rel.replace("/", "\\") if rel else "")
    return host_root + ("/" + rel if rel else "")


def resolve_workspace_local_path(workspace_id: str, ctx=None) -> Optional[str]:
    """Return the navigable on-disk path for a *local* (filesystem) workspace.

    Only local workspaces live at a navigable OS path; NextCloud and other
    fsspec backends return None. Resolution order (each independent of the
    others, so a mis-set USECASES_DIR can't hide the path):

    1. ``ctx``, when the caller already holds the workspace's live
       WorkspaceContext (the authoritative root — always matches the running
       app's config).
    2. A fresh registry lookup by id.
    3. A direct scan of candidate local roots for
       ``<root>/<id>/workspace_meta/metadata.json``.

    The resolved path may be a *container* path when running in Docker; it is
    translated to the host path (see ``to_host_display_path``) so the user can
    open it on their own machine.
    """
    resolved = None

    # 1. Caller-supplied context (only if it's the workspace we're asking about).
    if ctx is not None and getattr(ctx, "id", None) == workspace_id:
        resolved = native_local_path(ctx)

    # 2. Registry lookup.
    if not resolved:
        try:
            from .registry import load_registry
            resolved = native_local_path(load_registry().by_id(workspace_id))
        except Exception:
            pass

    # 3. Filesystem scan of candidate roots.
    if not resolved:
        for root in candidate_local_roots():
            candidate = os.path.join(root, workspace_id)
            marker = os.path.join(candidate, "workspace_meta", "metadata.json")
            if os.path.isfile(marker):
                resolved = os.path.normpath(candidate)
                break

    if not resolved:
        return None
    return to_host_display_path(resolved) or resolved
