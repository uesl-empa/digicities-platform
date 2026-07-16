# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/service_catalog.py
"""Shared discovery + reading of service-requirement YAMLs.

Service requirement definitions live in two places:

- the active workspace's ``services/`` folder (read via ``ctx.storage``)
- the global services library (NextCloud ``global/services/``)

This module is the single implementation for listing and reading them, so the
Scenario Builder, Replica Builder service guide, Service Requirements Builder,
and API submission tab all share one code path instead of duplicating the
glob / NextCloud-list logic (which had drifted apart, even using different
client methods).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml
import streamlit as st


@dataclass
class ServiceRef:
    """A discovered service definition.

    - ``name``     : the YAML ``service_name`` (else derived from the filename)
    - ``source``   : ``"workspace"`` or ``"global"``
    - ``filename`` : bare file name (e.g. ``WindForecasting.yaml``)
    - ``ref``      : workspace-relative path, or ``services/<filename>`` for global
    - ``content``  : parsed YAML dict, or ``None`` if it could not be parsed
    """
    name: str
    source: str
    filename: str
    ref: str
    content: Optional[dict] = None


def _active_storage():
    ctx = st.session_state.get("workspace_context")
    return getattr(ctx, "storage", None) if ctx is not None else None


def _global_client():
    try:
        from components.nextcloud_global_client import get_global_nextcloud_client
        return get_global_nextcloud_client()
    except Exception:
        return None


def _local_global_dir() -> Optional[Path]:
    """Local global-services directory (a fallback for the NextCloud global library
    that works without NextCloud). Service YAMLs here appear in EVERY workspace's
    dropdown. Path from ``GLOBAL_SERVICES_DIR`` (default ``data/global_services``)."""
    d = Path(os.environ.get("GLOBAL_SERVICES_DIR", "data/global_services"))
    try:
        return d if d.is_dir() else None
    except Exception:
        return None


def _derive_name(content, filename: str) -> str:
    if isinstance(content, dict) and content.get("service_name"):
        return content["service_name"]
    return filename.rsplit(".", 1)[0].replace("_", " ").title()


def list_workspace_services(storage=None) -> List[ServiceRef]:
    """Service YAMLs in the active workspace's ``services/`` folder."""
    storage = storage if storage is not None else _active_storage()
    out: List[ServiceRef] = []
    if storage is None:
        return out
    try:
        if not storage.exists("services"):
            return out
        rels = list(storage.glob("services/*.yaml")) + list(storage.glob("services/*.yml"))
    except Exception:
        return out
    for rel in rels:
        try:
            content = yaml.safe_load(storage.read_text(rel))
        except Exception:
            content = None
        fname = rel.rsplit("/", 1)[-1]
        out.append(ServiceRef(_derive_name(content, fname), "workspace", fname, rel,
                              content if isinstance(content, dict) else None))
    return out


def list_global_services() -> List[ServiceRef]:
    """Global service YAMLs: a local ``data/global_services`` directory (works
    without NextCloud) plus the NextCloud global library when configured."""
    out: List[ServiceRef] = []

    # Local global-services directory.
    d = _local_global_dir()
    if d is not None:
        try:
            paths = sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml")))
        except Exception:
            paths = []
        for p in paths:
            try:
                content = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                content = None
            out.append(ServiceRef(_derive_name(content, p.name), "global", p.name,
                                  str(p), content if isinstance(content, dict) else None))

    # NextCloud global library.
    client = _global_client()
    if not client:
        return out
    try:
        filenames = [f for f in (client.list_services_files() or [])
                     if f.endswith((".yaml", ".yml"))]
    except Exception:
        return out
    for fname in filenames:
        content = None
        try:
            text = client.get_service_file_content(fname)
            content = yaml.safe_load(text) if text else None
        except Exception:
            content = None
        out.append(ServiceRef(_derive_name(content, fname), "global", fname,
                              f"global/services/{fname}",
                              content if isinstance(content, dict) else None))
    return out


def list_services(global_first: bool = True) -> List[ServiceRef]:
    """Workspace + global services together."""
    workspace = list_workspace_services()
    glob = list_global_services()
    return (glob + workspace) if global_first else (workspace + glob)


def services_by_name(global_first: bool = True) -> Dict[str, ServiceRef]:
    """All services keyed by name; on a name collision the first wins
    (``global_first`` controls precedence)."""
    out: Dict[str, ServiceRef] = {}
    for ref in list_services(global_first=global_first):
        out.setdefault(ref.name, ref)
    return out


def read_service_text(ref: ServiceRef) -> Optional[str]:
    """Raw YAML text for a ServiceRef (from its known source)."""
    if ref.source == "global":
        # Local global-services file (ref is its path).
        try:
            p = Path(ref.ref)
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
        client = _global_client()
        if client:
            try:
                return client.get_service_file_content(ref.filename)
            except Exception:
                return None
    elif ref.source == "workspace":
        storage = _active_storage()
        if storage is not None:
            try:
                if storage.exists(ref.ref):
                    return storage.read_text(ref.ref)
            except Exception:
                return None
    return None
