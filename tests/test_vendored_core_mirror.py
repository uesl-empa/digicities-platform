# SPDX-License-Identifier: Apache-2.0
"""The two vendored copies of the core ontology must be the same file.

`data/ontology/` is what the agent, the Ontology Manager and the workspace
merges read; `services/graphdb/ontology/` is what provisioning loads into every
workspace graph (and what seeds the triplestore container). The v0.3.0
(collections) and v0.4.0 (Observation) re-vendors updated only the first, so
the graph ran on v0.2.0: a class the agent put under `Observation` never
reached `Component`, the explorer and scenario sync could not see its
instances, and sync dropped every one of them from the scenario.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "ontology"
SERVICES = ROOT / "services" / "graphdb" / "ontology"


def test_the_graph_loads_the_same_core_the_agent_maps_against():
    assert (SERVICES / "dici_onto_core.ttl").read_bytes() == (DATA / "dici_onto_core.ttl").read_bytes()


def test_the_qudt_units_are_mirrored_too():
    assert (SERVICES / "qudt_units.txt").read_bytes() == (DATA / "imports" / "qudt_units.txt").read_bytes()


def test_the_version_pin_names_the_vendored_release():
    ttl = (SERVICES / "dici_onto_core.ttl").read_text(encoding="utf-8")
    version = re.search(r'owl:versionInfo\s+"([^"]+)"', ttl).group(1)
    assert (SERVICES / "VERSION").read_text(encoding="utf-8").strip() == f"v{version}"
