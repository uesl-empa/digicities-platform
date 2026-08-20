# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Unit and currency IRIs as display strings, for the explorer table.

``backend.units`` stays authoritative on what counts as "no unit at all"
(``is_missing_unit``) and on round-trippable QUDT codes. The mappings here are
explorer-specific display sugar on top of that: turning ``unit:MegaW`` into
``MW`` for a table cell, and currency IRIs (current QUDT ``cur:`` and legacy
``iso4217:`` spellings alike) into their three-letter codes.
"""

from typing import Dict, Tuple

from backend.explorer.uris import extract_uri_fragment


def clean_unit(unit_value: str) -> str:
    """A displayable unit string, or '' when there is no unit.

    ``unit:None``, the bare QUDT namespace and friends are absences dressed up as
    units (backend.units explains where each comes from); rendering one as an axis
    label shows the user something that isn't true.
    """
    from backend.units import is_missing_unit
    if is_missing_unit(unit_value):
        return ''
    text = map_unit_uri_to_string(str(unit_value).strip())
    # A bare IRI that mapped to nothing still leaves the local name to show.
    if text.startswith('http'):
        text = text.rstrip('/').rsplit('/', 1)[-1]
    return '' if is_missing_unit(text) else text


def curve_axis_units(props: Dict) -> Tuple[str, str]:
    """(x_unit, y_unit) for a curve, preferring the string labels over the IRIs.

    Both are optional and independently so: the Replica Builder writes only the
    IRIs, the Excel ingestion writes both, and a dimensionless axis (a thrust
    coefficient) legitimately has neither.
    """
    x = clean_unit(props.get('xUnitLabel', '')) or clean_unit(props.get('xUnit', ''))
    y = clean_unit(props.get('yUnitLabel', '')) or clean_unit(props.get('yUnit', ''))
    return x, y


def map_unit_uri_to_string(unit_uri: str) -> str:
    """Map QUDT unit URIs to readable strings, including custom ratios - ENHANCED"""
    if not unit_uri:
        return ''

    # Check if it's a custom ratio format (e.g., "KiloGM/KiloW")
    if '/' in unit_uri and not unit_uri.startswith('http'):
        return unit_uri

    # Check for -PER- format (e.g., "KiloGM-PER-KiloW")
    if '-PER-' in unit_uri:
        return unit_uri.replace('-PER-', '/')

    # Standard unit mappings
    unit_mapping = {
        'http://qudt.org/vocab/unit/MegaW': 'MW',
        'http://qudt.org/vocab/unit/KiloW': 'kW',
        'http://qudt.org/vocab/unit/W': 'W',
        'http://qudt.org/vocab/unit/M': 'm',
        'http://qudt.org/vocab/unit/DEG': '°',
        'http://qudt.org/vocab/unit/M-PER-SEC': 'm/s',
        'http://qudt.org/vocab/unit/N': 'N',
        'http://qudt.org/vocab/unit/ONE': '',
        'http://qudt.org/vocab/unit/W-M2': 'W/m²',
        'http://qudt.org/vocab/unit/W-HR': 'Wh',
        'http://qudt.org/vocab/unit/KiloW-HR': 'kWh',
        'http://qudt.org/vocab/unit/kWh': 'kWh',  # Added common variant
        'http://qudt.org/vocab/unit/KiloGM': 'kg',
        'http://qudt.org/vocab/unit/KiloGM-PER-KiloW': 'kg/kW',
    }

    # Exact match
    if unit_uri in unit_mapping:
        return unit_mapping[unit_uri]

    # Handle unit: prefix
    if unit_uri.startswith('unit:'):
        local_unit = unit_uri.replace('unit:', '')
        if '-PER-' in local_unit:
            return local_unit.replace('-PER-', '/')
        # Try to match with full URI
        for full_uri, symbol in unit_mapping.items():
            if full_uri.endswith(local_unit):
                return symbol

    # Extract fragment as fallback
    return extract_uri_fragment(unit_uri)


def map_currency_uri_to_string(currency_uri: str) -> str:
    """Map currency URIs to readable strings"""
    if not currency_uri:
        return ''

    currency_mapping = {
        # Current — QUDT currency vocabulary
        'http://qudt.org/vocab/currency/CHF': 'CHF',
        'http://qudt.org/vocab/currency/EUR': 'EUR',
        'http://qudt.org/vocab/currency/USD': 'USD',
        'cur:CHF': 'CHF',
        'cur:EUR': 'EUR',
        'cur:USD': 'USD',
        # Legacy — pre-cur switch
        'http://example.org/currency/CHF': 'CHF',
        'http://example.org/currency/EUR': 'EUR',
        'http://example.org/currency/USD': 'USD',
        'iso4217:CHF': 'CHF',
        'iso4217:EUR': 'EUR',
        'iso4217:USD': 'USD',
    }

    if currency_uri in currency_mapping:
        return currency_mapping[currency_uri]

    return extract_uri_fragment(currency_uri)
