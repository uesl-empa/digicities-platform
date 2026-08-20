# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: the NextCloud client moved to ``backend.nextcloud.client``."""

from backend.nextcloud.client import (  # noqa: F401
    NextcloudClient,
    create_client_from_env,
    quick_read_timeseries,
    test_client_basic_functionality,
)
