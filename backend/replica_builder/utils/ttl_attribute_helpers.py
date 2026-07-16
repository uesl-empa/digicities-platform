# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/utils/ttl_attribute_helpers.py
"""
Shared TTL generation helpers for attribute types.

This is the single source of truth for converting session-state attribute dicts
into Turtle RDF lines.  Both replica_ttl_generator.py and any future consumers
should import from here so that changes to any attribute type's TTL representation
only need to be made in one place.

Attribute data dict keys by type
---------------------------------
Physical / DynamicAttribute:
    value, unit, datasource, historic_reference, future_reference, live_reference

Categorical:
    category_value

Event:
    temporal_value, temporal_precision, datasource

SimpleCost:
    value, currency, datasource

UnitBasedCost:
    value, unit, currency, datasource

Curve:
    x_unit, y_unit, data_points, datasource

Resource:
    data_path

SimpleValue:
    value, datasource

CustomPhysicalRatio:
    value, custom_unit  (format: "NumeratorUnit/DenominatorUnit", e.g. "KiloW-HR/M2")

Identifier:
    identifier_value

Geospatial:
    value, datasource
"""

from typing import Dict, List


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def format_decimal(num: float) -> str:
    """Format a float for TTL xsd:decimal literals."""
    if isinstance(num, float):
        if num.is_integer():
            return f"{int(num)}.0"
        return f"{num}"
    return str(num)


def escape_ttl_string(s: str) -> str:
    """Escape a Python string for use inside TTL double-quoted literals."""
    s = str(s)
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    s = s.replace('\r', '\\r')
    return s


def process_curve_data_string(data_str: str) -> List[str]:
    """Parse a curve data string into formatted point strings.

    Expected input format:  [(x1,y1);(x2,y2);...]
    Returns a list of formatted strings like '[   1.0,      2.5],'
    """
    import re
    if not data_str:
        return []

    try:
        data_str = data_str.strip('[]')
        points_str = data_str.split(';')

        formatted_points = []
        for point_str in points_str:
            match = re.match(r'\((\d+\.?\d*),(\d+\.?\d*)\)', point_str.strip())
            if match:
                x_str = format_decimal(float(match.group(1)))
                y_str = format_decimal(float(match.group(2)))
                formatted_points.append(f'[{x_str:>8}, {y_str:>10}],')

        if formatted_points:
            formatted_points[-1] = formatted_points[-1].rstrip(',')

        return formatted_points
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Core attribute TTL generator
# ---------------------------------------------------------------------------

def generate_attribute_ttl(attr_uri: str, attr_name: str, attr_data: Dict, component_type: str) -> List[str]:
    """Return a list of TTL lines representing a single attribute resource.

    This is the canonical implementation.  All attribute-type-specific TTL
    logic lives here; callers must not duplicate it.
    """
    lines = []
    attr_type = attr_data.get('type', 'Physical')

    if attr_type == "Physical":
        attr_properties = [f"a dici_onto:{attr_name}"]

        has_time_series = (
            'historic_reference' in attr_data or
            'future_reference' in attr_data or
            'live_reference' in attr_data
        )

        if has_time_series:
            attr_properties.append("a dici_onto:DynamicAttribute")
        else:
            attr_properties.append("a dici_onto:PhysicalAttribute")

        if attr_data.get('unit'):
            unit = attr_data['unit']
            attr_properties.append(f"qudt:unit <http://qudt.org/vocab/unit/{unit}>")
            attr_properties.append(f'dici_onto:hasUnitLabel "{unit}"^^xsd:string')

        if 'datasource' in attr_data:
            attr_properties.append(
                f"dcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string"
            )

        value = attr_data.get('value')
        has_value = (
            value is not None and
            value != '' and
            not (isinstance(value, (int, float)) and value == 0)
        )
        if has_value:
            if isinstance(value, (int, float)):
                attr_properties.append(f'qudt:value "{format_decimal(float(value))}"^^xsd:decimal')
            else:
                attr_properties.append(f'qudt:value "{escape_ttl_string(value)}"^^xsd:string')

        ts_declarations = []

        # Historic
        if attr_data.get('historic_reference'):
            ts_uri = f"{attr_uri}_historic/ts"
            ref = attr_data['historic_reference']
            attr_properties.append(f"dici_onto:hasHistoricTimeSeries <{ts_uri}>")
            attr_properties.append(
                f'dici_onto:hasHistoricTimeSeriesReference "{escape_ttl_string(ref)}"^^xsd:string'
            )
            ts_lines = [
                f"<{ts_uri}> a dici_onto:TimeSeries ;",
                f'\tdici_onto:storedAt "{escape_ttl_string(ref)}"^^xsd:string ;',
                f'\tdici_onto:hasFileName "{escape_ttl_string(ref)}"^^xsd:string',
            ]
            if attr_data.get('unit'):
                unit = attr_data['unit']
                ts_lines[-1] += ' ;'
                ts_lines.append(f'\tqudt:unit <http://qudt.org/vocab/unit/{unit}> ;')
                ts_lines.append(f'\tdici_onto:hasUnitLabel "{unit}"^^xsd:string .')
            else:
                ts_lines[-1] += ' .'
            ts_declarations.extend(ts_lines)
            ts_declarations.append("")

        # Future
        if attr_data.get('future_reference'):
            ts_uri = f"{attr_uri}_future/ts"
            ref = attr_data['future_reference']
            attr_properties.append(f"dici_onto:hasFutureTimeSeries <{ts_uri}>")
            attr_properties.append(
                f'dici_onto:hasFutureTimeSeriesReference "{escape_ttl_string(ref)}"^^xsd:string'
            )
            ts_lines = [
                f"<{ts_uri}> a dici_onto:TimeSeries ;",
                f'\tdici_onto:storedAt "{escape_ttl_string(ref)}"^^xsd:string ;',
                f'\tdici_onto:hasFileName "{escape_ttl_string(ref)}"^^xsd:string',
            ]
            if attr_data.get('unit'):
                unit = attr_data['unit']
                ts_lines[-1] += ' ;'
                ts_lines.append(f'\tqudt:unit <http://qudt.org/vocab/unit/{unit}> ;')
                ts_lines.append(f'\tdici_onto:hasUnitLabel "{unit}"^^xsd:string .')
            else:
                ts_lines[-1] += ' .'
            ts_declarations.extend(ts_lines)
            ts_declarations.append("")

        # Live
        if attr_data.get('live_reference'):
            ts_uri = f"{attr_uri}_live/ts"
            ref = attr_data['live_reference']
            attr_properties.append(f"dici_onto:hasLiveTimeSeries <{ts_uri}>")
            attr_properties.append(
                f'dici_onto:hasLiveTimeSeriesReference "{escape_ttl_string(ref)}"^^xsd:string'
            )
            ts_lines = [
                f"<{ts_uri}> a dici_onto:TimeSeries ;",
                f'\tdici_onto:realTimeSource "{escape_ttl_string(ref)}"^^xsd:string',
            ]
            if attr_data.get('unit'):
                unit = attr_data['unit']
                ts_lines[-1] += ' ;'
                ts_lines.append(f'\tqudt:unit <http://qudt.org/vocab/unit/{unit}> ;')
                ts_lines.append(f'\tdici_onto:hasUnitLabel "{unit}"^^xsd:string .')
            else:
                ts_lines[-1] += ' .'
            ts_declarations.extend(ts_lines)
            ts_declarations.append("")

        # Assemble attribute block
        prop_lines = [f"<{attr_uri}> {attr_properties[0]}"]
        for prop in attr_properties[1:]:
            prop_lines.append(f"\t{prop}")
        formatted_attr = " ;\n".join(prop_lines) + " ."
        lines = [formatted_attr]

        if ts_declarations:
            lines.append("")
            lines.extend(ts_declarations)

    elif attr_type == "Categorical":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:CategoricalAttribute ;")
        lines.append(f"\ta dici_onto:{attr_data.get('category_value', '')} .")

    elif attr_type == "Event":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:EventAttribute ;")

        precision = attr_data.get('temporal_precision', 'Year')
        lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:{precision} ;")

        xsd_type = {
            'Year': 'xsd:gYear',
            'YearMonth': 'xsd:gYearMonth',
            'Date': 'xsd:date',
            'DateTime': 'xsd:dateTime',
        }.get(precision, 'xsd:string')

        temporal_value = attr_data.get('temporal_value', '')
        lines.append(f'\tdici_onto:hasTemporalValue "{escape_ttl_string(temporal_value)}"^^{xsd_type}')

        if 'datasource' in attr_data:
            lines.append(f" ;\n\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string .")
        else:
            lines[-1] += " ."

    elif attr_type in ("SimpleCost", "UnitBasedCost"):
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:{attr_type}Attribute ;")

        decimal_str = format_decimal(float(attr_data.get('value', 0)))
        lines.append(f'\tqudt:value "{decimal_str}"^^xsd:decimal ;')

        if attr_type == "UnitBasedCost" and attr_data.get('unit'):
            unit = attr_data['unit']
            lines.append(f"\tqudt:unit <http://qudt.org/vocab/unit/{unit}> ;")
            lines.append(f'\tdici_onto:hasUnitLabel "{unit}"^^xsd:string ;')

        if 'datasource' in attr_data:
            lines.append(f"\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string ;")

        lines.append(f"\tdici_onto:currency cur:{attr_data.get('currency', 'CHF')} .")

    elif attr_type == "Curve":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:CurveAttribute ;")
        lines.append(f"\tdici_onto:xUnit unit:{attr_data.get('x_unit', 'M')} ;")
        lines.append(f"\tdici_onto:yUnit unit:{attr_data.get('y_unit', 'NUM')} ;")

        formatted_points = process_curve_data_string(attr_data.get('data_points', ''))
        lines.append('\tdici_onto:hasDataPoints """[')
        lines.extend([f'    {p}' for p in formatted_points])
        lines.append('    ]"""')

        if 'datasource' in attr_data:
            lines.append(f" ;\n\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string .")
        else:
            lines[-1] += " ."

    elif attr_type == "Resource":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:ResourceAttribute ;")
        lines.append(
            f'\tdici_onto:hasDataPath "{escape_ttl_string(attr_data.get("data_path", ""))}"^^xsd:string .'
        )

    elif attr_type == "SimpleValue":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:SimpleValueAttribute ;")

        if 'datasource' in attr_data:
            lines.append(f"\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string ;")

        value = attr_data.get('value', '')
        try:
            decimal_str = format_decimal(float(value))
            lines.append(f'\tdici_onto:hasAttributeValue "{decimal_str}"^^xsd:decimal .')
        except (ValueError, TypeError):
            lines.append(f'\tdici_onto:hasAttributeValue "{escape_ttl_string(value)}"^^xsd:string .')

    elif attr_type == "CustomPhysicalRatio":
        # Ratio units cannot be expressed as a single qudt:Unit IRI.
        # Use dici_onto:hasUnitLabel EXCLUSIVELY (not qudt:unit).
        # custom_unit format: "NumeratorUnit/DenominatorUnit" e.g. "KiloW-HR/M2"
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:CustomPhysicalRatioAttribute ;")

        if 'datasource' in attr_data:
            lines.append(f"\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string ;")

        decimal_str = format_decimal(float(attr_data.get('value', 0)))
        lines.append(f'\tqudt:value "{decimal_str}"^^xsd:decimal ;')
        lines.append(
            f'\tdici_onto:hasUnitLabel "{escape_ttl_string(attr_data.get("custom_unit", ""))}"^^xsd:string .'
        )

    elif attr_type == "Identifier":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(
            f'\tdici_onto:identifierValue "{escape_ttl_string(attr_data.get("identifier_value", ""))}" .'
        )

    elif attr_type == "Geospatial":
        lines.append(f"<{attr_uri}> a dici_onto:{attr_name} ;")
        lines.append(f"\ta dici_onto:GeospatialAttribute ;")

        if 'datasource' in attr_data:
            lines.append(f"\tdcterms:source \"{escape_ttl_string(attr_data['datasource'])}\"^^xsd:string ;")

        lines.append(
            f'\tdici_onto:hasAttributeValue "{escape_ttl_string(attr_data.get("value", ""))}"^^xsd:string .'
        )

    return lines
