# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Where workspaces live is a property of the INSTALLATION, not of each workspace.

``STORAGE_BACKEND`` decides it once for the whole platform:

* ``nextcloud`` — every workspace lives in NextCloud, the only persistent store.
  The folders in the server's workspaces folder are its working copies of them
  (see :mod:`backend.workspace.mirror`), never workspaces of their own.
* ``local`` (default) — for testing on your own machine: every workspace is a
  folder in the workspaces folder, which docker compose maps to a folder on your
  drive (``USECASES_HOST_PATH``) — shown in the UI so you can find the files.

There is no per-workspace choice: mixing the two let a NextCloud workspace's
working copy be registered as a local workspace, after which its changes
silently stopped reaching NextCloud.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def storage_backend() -> str:
    """``"nextcloud"`` or ``"local"`` — this installation's workspace store."""
    return "nextcloud" if os.getenv("STORAGE_BACKEND", "").strip().lower() == "nextcloud" \
        else "local"


def describe_storage() -> dict:
    """What the UI tells the user about where workspace files go.

    ``{"backend", "label", "location"}`` — for NextCloud the server's host (never
    credentials); for local storage the folder on the user's drive when compose
    passes it (``USECASES_HOST_PATH``), else the path inside the container."""
    if storage_backend() == "nextcloud":
        base = os.getenv("NEXTCLOUD_BASE_URL", "")
        host = urlparse(base).netloc or base
        return {"backend": "nextcloud", "label": "NextCloud",
                "location": host or "the configured NextCloud server"}
    from .paths import to_host_display_path
    from .registry import _usecases_dir
    ws_dir = str(_usecases_dir()).replace("\\", "/")
    return {"backend": "local", "label": "This computer",
            "location": to_host_display_path(ws_dir) or ws_dir}
