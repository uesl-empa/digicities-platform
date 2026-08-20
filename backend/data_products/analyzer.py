# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Pure resource-format sniffing and parsing for data-product resources.

Extracted from ``apps/streamlit/components/data_products/resource_analyzer.py``
(Phase 5, data-products half): everything here is Streamlit-free and returns
plain data, so both the Streamlit Resources tab and the REST API's
``GET …/data-products/{name}/resource`` endpoint share one implementation.
Rendering (plotly charts, st.* layout) stays on the Streamlit side.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

# Display metadata per file type (pure lookup; the Streamlit tab renders it).
TYPE_INFO: Dict[str, Dict[str, str]] = {
    'csv': {'emoji': '📊', 'description': 'Tabular data'},
    'geojson': {'emoji': '🗺️', 'description': 'Geographic data'},
    'json': {'emoji': '📄', 'description': 'Structured data'},
    'epw': {'emoji': '🌤️', 'description': 'Weather data'},
    'txt': {'emoji': '📝', 'description': 'Text data'},
    'xml': {'emoji': '🏷️', 'description': 'XML data'},
    'unknown': {'emoji': '❓', 'description': 'Unknown format'},
}


def get_type_info(file_type: str) -> Dict[str, str]:
    """Display information for a file type (same table the tab always used)."""
    return TYPE_INFO.get(file_type, TYPE_INFO['unknown'])


def detect_format(filename: str) -> str:
    """Sniff the resource format from the filename extension.

    ``geojson``/``json``/``csv``/``epw``/``txt`` come back as themselves;
    anything else is the bare lowercase extension ('' when there is none).
    """
    name = filename.lower()
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1]


def group_resources_by_type(resources: List[Dict]) -> Dict[str, List[Dict]]:
    """Group resource dicts (with a 'type' key) by file type."""
    grouped: Dict[str, List[Dict]] = {}
    for resource in resources:
        file_type = resource.get('type', 'unknown')
        grouped.setdefault(file_type, []).append(resource)
    return grouped


# ---------------------------------------------------------------- CSV helpers

def detect_datetime_columns(df: pd.DataFrame) -> List[str]:
    """Columns that parse as datetimes (sampled on the first 10 rows) — the
    detection the timeseries plot in the Resources tab uses."""
    datetime_cols: List[str] = []
    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                pd.to_datetime(df[col].head(10))
                datetime_cols.append(col)
            except Exception:
                pass
        elif 'datetime' in str(df[col].dtype):
            datetime_cols.append(col)
    return datetime_cols


def numeric_columns(df: pd.DataFrame) -> List[str]:
    import numpy as np

    return df.select_dtypes(include=[np.number]).columns.tolist()


def csv_preview(df: pd.DataFrame, max_rows: int = 500) -> Dict[str, Any]:
    """A JSON-safe preview of a DataFrame: columns + row dicts, capped.

    ``truncated`` says whether the cap bit; ``total_rows`` is the full length
    so callers can report "showing N of M".
    """
    head = df.head(max_rows)
    rows = head.astype(object).where(head.notna(), None).to_dict(orient='records')
    return {
        'columns': [str(c) for c in df.columns],
        'rows': rows,
        'total_rows': int(len(df)),
        'truncated': len(df) > max_rows,
        'max_rows': max_rows,
        'datetime_columns': detect_datetime_columns(df),
        'numeric_columns': numeric_columns(df),
    }


# ------------------------------------------------------------ GeoJSON helpers

def geojson_summary(data: Dict) -> Dict[str, Any]:
    """Type / feature count / available properties of a GeoJSON object."""
    geom_type = data.get('type', 'Unknown')
    summary: Dict[str, Any] = {'geojson_type': geom_type}
    if geom_type == 'FeatureCollection':
        features = data.get('features', [])
        summary['feature_count'] = len(features)
        props: set = set()
        for feature in features:
            props.update((feature.get('properties') or {}).keys())
        summary['properties'] = sorted(props)
    elif geom_type in ('Point', 'LineString', 'Polygon'):
        summary['coordinate_count'] = len(data.get('coordinates', []))
    return summary


# ---------------------------------------------------------------- EPW helpers

def epw_head(text: str, header_lines: int = 10) -> List[str]:
    """The EPW file header lines (non-empty, as the Resources tab shows them)."""
    lines = text.split('\n')
    return [line for line in lines[:header_lines] if line.strip()]


def epw_sample_rows(text: str, start: int = 8, count: int = 5) -> List[Dict[str, str]]:
    """A few parsed weather rows (Month/Day/Hour/Temperature/Humidity/Solar) —
    the same column picks the Resources tab previews."""
    lines = text.split('\n')
    rows: List[Dict[str, str]] = []
    for line in lines[start:start + count]:
        if ',' in line and len(line.split(',')) > 10:
            parts = line.split(',')
            rows.append({
                'Month': parts[1] if len(parts) > 1 else '',
                'Day': parts[2] if len(parts) > 2 else '',
                'Hour': parts[3] if len(parts) > 3 else '',
                'Temperature': parts[6] if len(parts) > 6 else '',
                'Humidity': parts[8] if len(parts) > 8 else '',
                'Solar': parts[13] if len(parts) > 13 else '',
            })
    return rows


# ------------------------------------------------------------- API projection

def resource_payload(data: Any, filename: str,
                     max_rows: int = 500, max_text: int = 10_000) -> Dict[str, Any]:
    """Project loaded resource data into a JSON-safe payload with a format tag.

    * DataFrame (CSV)      -> ``{'format': 'csv', columns, rows (capped), …}``
    * dict (GeoJSON/JSON)  -> the object itself plus a summary
    * str (EPW/text)       -> a text head, capped at ``max_text`` chars
    * bytes                -> length only (binaries aren't inlined as JSON)
    """
    fmt = detect_format(filename)
    if isinstance(data, pd.DataFrame):
        return {'format': 'csv', **csv_preview(data, max_rows=max_rows)}
    if isinstance(data, dict):
        tag = 'geojson' if data.get('type') in (
            'FeatureCollection', 'Feature', 'Point', 'LineString', 'Polygon',
            'MultiPoint', 'MultiLineString', 'MultiPolygon', 'GeometryCollection',
        ) else (fmt or 'json')
        payload: Dict[str, Any] = {'format': tag, 'content': data}
        if tag == 'geojson':
            payload['summary'] = geojson_summary(data)
        return payload
    if isinstance(data, str):
        payload = {
            'format': fmt or 'text',
            'text': data[:max_text],
            'length': len(data),
            'truncated': len(data) > max_text,
        }
        if fmt == 'epw':
            payload['header'] = epw_head(data)
            payload['sample_rows'] = epw_sample_rows(data)
        return payload
    if isinstance(data, (bytes, bytearray)):
        return {'format': fmt or 'binary', 'length': len(data), 'binary': True}
    return {'format': fmt or 'unknown', 'text': str(data)[:max_text]}


__all__ = [
    'TYPE_INFO', 'get_type_info', 'detect_format', 'group_resources_by_type',
    'detect_datetime_columns', 'numeric_columns', 'csv_preview',
    'geojson_summary', 'epw_head', 'epw_sample_rows', 'resource_payload',
]
