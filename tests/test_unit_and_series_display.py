# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Unit display fallbacks and time-series metadata surfacing."""
from __future__ import annotations

from backend.explorer import AttributeProcessor, map_unit_uri_to_string


def test_full_uri_per_units_do_not_leak_the_scheme():
    # The -PER- shortcut used to fire on the full URI, displaying
    # "http://qudt.org/vocab/unit/KM/HR" in the tables.
    assert map_unit_uri_to_string('http://qudt.org/vocab/unit/KM-PER-HR') == 'km/h'


def test_unknown_full_uri_falls_back_to_local_name():
    assert map_unit_uri_to_string('http://qudt.org/vocab/unit/FT-PER-SEC') == 'FT/SEC'
    assert map_unit_uri_to_string('http://qudt.org/vocab/unit/PA') == 'PA'


def test_bare_per_code_keeps_its_spelling():
    assert map_unit_uri_to_string('KiloGM-PER-KiloW') == 'KiloGM/KiloW'


def test_dynamic_attribute_stashes_series_meta():
    p = AttributeProcessor()
    p.series_meta = {}
    label = p._process_dynamic_attribute(
        {'properties': {'hasHistoricTimeSeriesReference': 'resources/counts.csv',
                        'unit': 'http://qudt.org/vocab/unit/KM-PER-HR'}},
        'Power')
    assert label.startswith('Historic Time Series')
    assert p.series_meta['Power'] == {
        'kind': 'Historic', 'reference': 'resources/counts.csv', 'unit': 'km/h'}


def test_dynamic_attribute_without_reference_stays_blank():
    p = AttributeProcessor()
    p.series_meta = {}
    assert p._process_dynamic_attribute({'properties': {}}, 'Empty') is None
    assert p.series_meta == {}
