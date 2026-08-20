# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Regression guard for the QUDT-unit round-trip (fix 570bd6c / 06c90a3).

The workspace TTL loader must surface QUDT unit *codes* (``KiloW``,
``KiloW-HR``), never lossy display abbreviations (``kW``) — abbreviations can't
be turned back into valid ``qudt:unit`` IRIs by the TTL emitters and used to
degrade to ``UNITLESS``. The loader lives in a Streamlit component module
(``apps/streamlit`` is on sys.path via tests/conftest.py).
"""
from __future__ import annotations

from components.scenario_builder.ttl_use_case_loader import (
    NextCloudTTLUseCaseLoader,
)

_map = NextCloudTTLUseCaseLoader._map_unit_uri_to_string


class _Stub:
    """The method doesn't touch instance state; call it unbound via a stub."""


def _code(uri: str) -> str:
    return _map(_Stub(), uri)


def test_full_uri_returns_qudt_code():
    assert _code("http://qudt.org/vocab/unit/KiloW") == "KiloW"
    assert _code("http://qudt.org/vocab/unit/KiloW-HR") == "KiloW-HR"
    assert _code("http://qudt.org/vocab/unit/M-PER-SEC") == "M-PER-SEC"


def test_curie_returns_qudt_code():
    assert _code("unit:KiloW") == "KiloW"
    assert _code("unit:KiloW-HR") == "KiloW-HR"


def test_no_lossy_abbreviations():
    # The historical failure mode: KiloW -> kW -> emitted as <.../kW> / UNITLESS.
    for uri in ("http://qudt.org/vocab/unit/KiloW", "unit:KiloW"):
        assert _code(uri) != "kW"
