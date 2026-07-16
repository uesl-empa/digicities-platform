# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
GraphDB backend package.

Pure Python SPARQL/RDF client for the Digicities platform. No Streamlit
dependency — safe to import from notebooks, CLI tools, or services.
"""

from backend.graphdb.client import (
    GraphDBClient,
    Transaction,
    UnifiedGraphDBClient,
)
from backend.graphdb.utils import (
    df_from_json,
    dict_from_json,
    save_debug_report,
    split_graph,
)

__all__ = [
    "GraphDBClient",
    "Transaction",
    "UnifiedGraphDBClient",
    "df_from_json",
    "dict_from_json",
    "save_debug_report",
    "split_graph",
]
