# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Clean data processing utilities for the Component Explorer
This file replaces the existing data_processing.py
"""

import pandas as pd
import ast
import json
import re
from typing import Dict, List, Any, Optional


def process_component_data(result_data: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Process component data from SPARQL results into a DataFrame
    This function maintains compatibility with the original interface
    """
    if not result_data:
        return pd.DataFrame()

    # Group data by component instance
    instances = {}

    for item in result_data:
        instance_uri = item.get('instance', {}).get('value', '')
        property_uri = item.get('property', {}).get('value', '')
        value = item.get('value', {}).get('value', '')

        if not instance_uri:
            continue

        if instance_uri not in instances:
            instances[instance_uri] = {
                'URI': instance_uri,
                'instance_id': instance_uri.split('/')[-1] if '/' in instance_uri else instance_uri
            }

        # Extract property name and store value
        property_name = property_uri.split('#')[-1].split('/')[-1] if property_uri else 'unknown'
        if property_name and property_name != 'type':  # Skip rdf:type
            instances[instance_uri][property_name] = value

    if not instances:
        return pd.DataFrame()

    # Convert to DataFrame
    df = pd.DataFrame.from_dict(instances, orient='index')
    df.reset_index(drop=True, inplace=True)

    return df


def parse_curve_data(curve_data_str: str) -> List[tuple]:
    """
    Parse curve data from string format to list of (x, y) points
    Supports multiple formats including JSON arrays and Python lists
    """
    if not curve_data_str or pd.isna(curve_data_str):
        return []

    try:
        # Clean up the string
        cleaned = re.sub(r'\s+', ' ', str(curve_data_str).strip())

        # Try parsing as Python literal (list of lists/tuples)
        if cleaned.startswith('[') and cleaned.endswith(']'):
            try:
                points = ast.literal_eval(cleaned)
                if isinstance(points, list) and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in points):
                    return [(float(p[0]), float(p[1])) for p in points]
            except (ValueError, SyntaxError):
                pass

        # Try parsing as JSON
        try:
            points = json.loads(cleaned)
            if isinstance(points, list) and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in points):
                return [(float(p[0]), float(p[1])) for p in points]
        except (json.JSONDecodeError, ValueError):
            pass

        # Try regex extraction for format like [[1.0, 0.0], [2.0, 3000.0], ...]
        point_pattern = r'\[\s*([0-9.-]+)\s*,\s*([0-9.-]+)\s*\]'
        matches = re.findall(point_pattern, cleaned)
        if matches:
            return [(float(x), float(y)) for x, y in matches]

    except Exception as e:
        print(f"Error parsing curve data: {e}")

    return []


def get_visible_columns(df: pd.DataFrame) -> List[str]:
    """
    Get columns that should be visible in the table display
    Excludes system/internal columns that aren't useful for users
    """
    if df.empty:
        return []

    # Always include these essential columns
    essential_columns = ['URI', 'instance_id']
    visible_columns = []

    for col in df.columns.tolist():
        # Include essential columns
        if col in essential_columns:
            visible_columns.append(col)
        # Include other meaningful columns (exclude internal/system ones)
        elif not col.startswith('_') and col not in ['type', 'Type']:
            visible_columns.append(col)

    return visible_columns


def format_attribute_value(value: Any) -> str:
    """
    Format attribute values for better display in tables
    """
    if pd.isna(value) or value is None or value == '':
        return 'N/A'

    # Convert to string and handle long values
    str_value = str(value)

    # Truncate very long values for table display
    if len(str_value) > 200:
        return f"{str_value[:197]}..."

    return str_value


def extract_units_from_column_name(column_name: str) -> tuple:
    """
    Extract unit information from column names
    Returns (x_unit, y_unit) for curve data
    """
    if '_' in column_name:
        parts = column_name.split('_', 1)
        if len(parts) == 2:
            units_part = parts[1]
            if '/' in units_part:
                unit_parts = units_part.split('/')
                if len(unit_parts) == 2:
                    return unit_parts[1], unit_parts[0]  # x_unit, y_unit

    return 'Input', 'Output'  # Default labels


def create_summary_statistics(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Create summary statistics for the component data
    """
    if df.empty:
        return {}

    # Basic counts
    total_instances = len(df)
    total_attributes = len([col for col in df.columns if col not in ['URI', 'instance_id']])

    # Attribute coverage analysis
    coverage_stats = {}
    for col in df.columns:
        if col not in ['URI', 'instance_id']:
            non_null_count = df[col].notna().sum()
            coverage_pct = (non_null_count / total_instances) * 100 if total_instances > 0 else 0
            coverage_stats[col] = {
                'count': int(non_null_count),
                'percentage': round(coverage_pct, 1)
            }

    # Data type analysis
    type_counts = {
        'numeric': 0,
        'text': 0,
        'curve': 0
    }

    for col in df.columns:
        if col not in ['URI', 'instance_id']:
            if df[col].dtype in ['int64', 'float64']:
                type_counts['numeric'] += 1
            elif any(indicator in col.lower() for indicator in ['curve', 'profile', 'data']):
                type_counts['curve'] += 1
            else:
                type_counts['text'] += 1

    return {
        'total_instances': total_instances,
        'total_attributes': total_attributes,
        'coverage': coverage_stats,
        'attribute_types': type_counts
    }


def validate_component_data(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate component data and identify potential issues
    """
    validation_results = {
        'is_valid': True,
        'warnings': [],
        'errors': [],
        'suggestions': []
    }

    if df.empty:
        validation_results['is_valid'] = False
        validation_results['errors'].append("No data found")
        return validation_results

    # Check for required columns
    required_columns = ['URI']
    missing_required = [col for col in required_columns if col not in df.columns]
    if missing_required:
        validation_results['errors'].append(f"Missing required columns: {missing_required}")
        validation_results['is_valid'] = False

    # Check data quality
    if 'URI' in df.columns:
        if df['URI'].isna().any():
            validation_results['warnings'].append("Some instances have missing URIs")

        duplicate_uris = df['URI'].duplicated().sum()
        if duplicate_uris > 0:
            validation_results['warnings'].append(f"Found {duplicate_uris} duplicate URIs")

    # Check attribute coverage
    non_system_cols = [col for col in df.columns if col not in ['URI', 'instance_id']]
    if non_system_cols:
        avg_coverage = df[non_system_cols].notna().mean().mean() * 100
        if avg_coverage < 50:
            validation_results['warnings'].append(f"Low attribute coverage: {avg_coverage:.1f}%")
        elif avg_coverage > 90:
            validation_results['suggestions'].append("Excellent data coverage!")
    else:
        validation_results['warnings'].append("No attribute data found beyond system columns")

    return validation_results