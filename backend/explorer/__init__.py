# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Digital Replica Explorer, the data half.

Everything the explorer does that is not rendering lives here: fetching
component types and their instances (via ``backend.graphdb.queries``), turning
attribute rows into the display table, parsing curve literals, mapping unit and
currency IRIs to readable strings, and shaping provenance. The Streamlit page
(``apps/streamlit/components/component_explorer.py``) and the REST API
(``apps/api``) both consume this package, so it must never import Streamlit.
"""

from backend.explorer.uris import (
    extract_property_name,
    extract_readable_instance_name,
    extract_uri_fragment,
)
from backend.explorer.units import (
    clean_unit,
    curve_axis_units,
    map_currency_uri_to_string,
    map_unit_uri_to_string,
)
from backend.explorer.attributes import (
    CURVE_META_PREFIX,
    AttributeProcessor,
    curve_columns,
    curve_data_is_reference,
    get_visible_columns,
    parse_curve_data,
    process_enhanced_component_data,
    structured_instance_attributes,
)
from backend.explorer.instances import (
    get_catalogue_instance_uris,
    get_component_attributes_comprehensive,
    get_component_basic_properties,
    get_component_data_unified,
    get_component_instances,
    get_component_types_with_instances,
)
from backend.explorer.provenance import (
    SOURCE_COLUMN,
    SOURCE_META_COLUMN,
    SOURCE_OPENERS,
    attach_sources,
    get_component_sources,
    open_source,
    resolve_workspace_file,
    summarize_sources,
)

__all__ = [
    "AttributeProcessor",
    "CURVE_META_PREFIX",
    "SOURCE_COLUMN",
    "SOURCE_META_COLUMN",
    "SOURCE_OPENERS",
    "attach_sources",
    "clean_unit",
    "curve_axis_units",
    "curve_columns",
    "curve_data_is_reference",
    "extract_property_name",
    "extract_readable_instance_name",
    "extract_uri_fragment",
    "get_component_attributes_comprehensive",
    "get_component_basic_properties",
    "get_catalogue_instance_uris",
    "get_component_data_unified",
    "get_component_instances",
    "get_component_sources",
    "get_component_types_with_instances",
    "get_visible_columns",
    "map_currency_uri_to_string",
    "map_unit_uri_to_string",
    "open_source",
    "parse_curve_data",
    "process_enhanced_component_data",
    "structured_instance_attributes",
    "resolve_workspace_file",
    "summarize_sources",
]
