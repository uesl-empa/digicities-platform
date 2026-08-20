# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Compatibility shim: these helpers moved to ``backend.scenario_builder.display_utils``."""

from backend.scenario_builder.display_utils import (  # noqa: F401
    format_ttl_component_for_display,
    get_nested_property_from_ttl_component,
    get_uri_fragment,
)
