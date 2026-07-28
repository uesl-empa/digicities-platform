# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""The vendored global asset libraries must work offline out of the box.

A fresh local clone (no NextCloud) should show content: the open-data-products
library ships the MotelDB starter product, and the Replica Builder "Get
Template" button resolves to the tracked ingestion workbook. Guards both the
vendored assets and the local-fallback lookup order.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import rdflib

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "streamlit"))

PRODUCTS_DIR = REPO_ROOT / "data" / "global_open_data_products"
NS = "https://digicities.info/ontology#"


def test_moteldb_product_folder_follows_convention():
    ttl = PRODUCTS_DIR / "MotelDB" / "MotelDB.ttl"   # NAME/NAME.ttl
    assert ttl.is_file()


def test_moteldb_product_parses_with_components_and_references():
    g = rdflib.Graph()
    g.parse(PRODUCTS_DIR / "MotelDB" / "MotelDB.ttl", format="turtle")
    assert len(g) > 1000
    # It's a reference database: components carrying attributes, each backed by
    # citable References typed with core terms (Reference/hasReferenceType).
    refs = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(NS + "Reference")))
    assert refs, "MotelDB should carry dici_onto:Reference provenance instances"
    attrs = list(g.subjects(rdflib.URIRef(NS + "hasReferenceType"), None))
    assert attrs


def test_global_products_dir_listable_via_workspace_storage():
    from backend.workspace.storage import WorkspaceStorage
    storage = WorkspaceStorage.local(str(PRODUCTS_DIR))
    names = {str(e.get("name", "")).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
             for e in storage.ls("", detail=True)
             if isinstance(e, dict) and e.get("type") in ("directory", "dir")}
    assert "MotelDB" in names


def test_template_lookup_falls_back_to_tracked_workbook(monkeypatch):
    """With no env override and no drop-in file, the lookup must resolve to the
    canonical tracked ingestion workbook — the offline 'Get Template' path."""
    from components.replica_builder.replica_excel_importer import _local_template_bytes
    monkeypatch.delenv("REPLICA_BUILDER_TEMPLATE_FILE", raising=False)
    monkeypatch.chdir(REPO_ROOT)
    data = _local_template_bytes()
    assert data is not None
    assert data[:2] == b"PK"  # xlsx = zip container
    assert len(data) == (REPO_ROOT / "data" / "ingestion_template"
                         / "data_ingestion_template.xlsx").stat().st_size


def test_template_env_override_wins(monkeypatch, tmp_path):
    from components.replica_builder.replica_excel_importer import _local_template_bytes
    custom = tmp_path / "custom.xlsx"
    custom.write_bytes(b"PK-custom")
    monkeypatch.setenv("REPLICA_BUILDER_TEMPLATE_FILE", str(custom))
    assert _local_template_bytes() == b"PK-custom"
