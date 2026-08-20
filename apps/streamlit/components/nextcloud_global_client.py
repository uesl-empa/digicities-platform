# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: the global-library client moved to ``backend.nextcloud.global_client``."""

from backend.nextcloud.client import NextcloudClient  # noqa: F401
from backend.nextcloud.global_client import (  # noqa: F401
    NextcloudGlobalClient,
    get_global_nextcloud_client,
    test_global_client,
    test_services_access,
)
