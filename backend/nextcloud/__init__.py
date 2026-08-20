# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Raw NextCloud WebDAV clients (workspace files + the global library).

Moved here from ``apps/streamlit/components/`` so headless consumers (the
REST API, scripts, tests) can use them without a Streamlit runtime. The
old ``components.nextcloud_client`` / ``components.nextcloud_global_client``
paths remain as re-export shims.

Note: ``backend/workspace/storage.py`` (fsspec/webdav4) is the strategic
storage seam for workspace file I/O. These clients are deliberately NOT
unified with it yet — this move relocates them unchanged; convergence is a
later phase.
"""

from backend.nextcloud.client import (
    NextcloudClient,
    create_client_from_env,
    quick_read_timeseries,
)
from backend.nextcloud.global_client import (
    NextcloudGlobalClient,
    get_global_nextcloud_client,
)

__all__ = [
    "NextcloudClient",
    "NextcloudGlobalClient",
    "create_client_from_env",
    "get_global_nextcloud_client",
    "quick_read_timeseries",
]
