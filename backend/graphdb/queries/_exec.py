# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Shared query execution helper for the backend query layer."""

from __future__ import annotations

from typing import List

import pandas as pd


def run_df(client, query: str, columns: List[str]) -> pd.DataFrame:
    """Execute a SPARQL query and return a DataFrame, never raising.

    Returns an empty DataFrame with ``columns`` on a missing client, any error,
    or an empty result, so callers can always rely on the column schema.
    """
    empty = pd.DataFrame(columns=columns)
    if client is None:
        return empty
    try:
        result = client.sparql_api_query(query, out_format="df")
    except Exception as exc:  # network / SPARQL error — caller decides how to surface
        print(f"[graphdb.queries] query failed: {exc}")
        return empty
    if result is None or result.empty:
        return empty
    return result
