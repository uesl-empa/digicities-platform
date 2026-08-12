# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Loader for external UI modules — nav entries that live outside this repo.

An external module is a folder mounted into the container that carries a
``module.yaml`` manifest next to a Python package:

    my-module/                  # ← the module folder (e.g. a cloned repo)
    ├── module.yaml             # manifest, see below
    ├── requirements.txt        # extra pip deps (installed by the compose
    │                           #   override's startup loop, not by this loader)
    └── my_module/              # the package named by `entry`
        └── __init__.py         # exposes the entry function

``MODULES_DIR`` (default ``/app/data/modules``, mounted from the host via
``MODULES_HOST_PATH`` in ``docker-compose.override.yml``) may either BE a module
folder or CONTAIN module folders one level deep — so pointing
``MODULES_HOST_PATH`` straight at a cloned module repo works.

Manifest (``module.yaml``)::

    name: onboarding-agent            # required, unique id
    label: "Onboarding Agent"         # nav label (default: name)
    description: One-line purpose.    # shown as tooltip/caption
    entry: onboarding_agent           # required, importable package/module name
    function: render                  # callable in `entry` (default: render),
                                      #   signature fn(client) — client is the
                                      #   workspace-scoped triplestore client
                                      #   (may be None when not connected)
    requires_env: [ANTHROPIC_API_KEY] # env vars that must be set to run

The module runs inside the platform's Streamlit process: it can read
``st.session_state`` (``current_workspace``, ``workspace_context``) and import
``backend.*`` — the same contract the built-in components have.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import streamlit as st
import yaml

MODULES_DIR = os.getenv("MODULES_DIR", "/app/data/modules")


def _read_manifest(folder: Path) -> dict | None:
    """Parse ``folder/module.yaml`` into a manifest dict, or None if invalid."""
    manifest_path = folder / "module.yaml"
    if not manifest_path.is_file():
        return None
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"[external_modules] unreadable manifest {manifest_path}: {exc}")
        return None
    if not isinstance(raw, dict) or not raw.get("name") or not raw.get("entry"):
        print(f"[external_modules] manifest {manifest_path} missing 'name' or 'entry'")
        return None
    return {
        "name": str(raw["name"]),
        "label": str(raw.get("label") or raw["name"]),
        "description": str(raw.get("description", "")),
        "entry": str(raw["entry"]),
        "function": str(raw.get("function") or "render"),
        "requires_env": [str(v) for v in (raw.get("requires_env") or [])],
        "folder": str(folder),
    }


def discover_external_modules() -> list[dict]:
    """Manifests of every external module under ``MODULES_DIR``.

    Accepts both layouts: MODULES_DIR itself being a module folder, or holding
    module folders one level deep. Returns [] when the dir is absent/empty, so
    a stock install is unaffected.
    """
    root = Path(MODULES_DIR)
    if not root.is_dir():
        return []
    manifests = []
    own = _read_manifest(root)
    if own:
        manifests.append(own)
    else:
        for sub in sorted(root.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")):
                m = _read_manifest(sub)
                if m:
                    manifests.append(m)
    # De-duplicate labels defensively — the nav radio needs unique options.
    seen: set[str] = set()
    unique = []
    for m in manifests:
        if m["label"] in seen:
            print(f"[external_modules] duplicate label '{m['label']}' — skipping {m['folder']}")
            continue
        seen.add(m["label"])
        unique.append(m)
    return unique


def find_external_module(label: str) -> dict | None:
    """The discovered manifest whose nav label is ``label``, or None."""
    return next((m for m in discover_external_modules() if m["label"] == label), None)


def render_external_module(manifest: dict, client) -> None:
    """Import and run an external module's entry function inside the app."""
    missing = [v for v in manifest["requires_env"] if not os.getenv(v)]
    if missing:
        st.error(
            f"**{manifest['label']}** needs environment variable(s) "
            f"{', '.join(f'`{v}`' for v in missing)}. Add them to `.env` and restart "
            "(`docker compose up -d`)."
        )
        return

    folder = manifest["folder"]
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        module = importlib.import_module(manifest["entry"])
    except ModuleNotFoundError as exc:
        req = Path(folder) / "requirements.txt"
        hint = (
            f" Its dependencies install from `{req}` at container start "
            "(see the modules section of `docker-compose.override.yml`) — restart the "
            "stack with `docker compose up -d` after mounting the module."
            if req.is_file() else ""
        )
        st.error(f"**{manifest['label']}** failed to import: `{exc}`.{hint}")
        return

    fn = getattr(module, manifest["function"], None)
    if not callable(fn):
        st.error(
            f"**{manifest['label']}**: entry `{manifest['entry']}` has no callable "
            f"`{manifest['function']}` (set `function:` in its module.yaml)."
        )
        return
    fn(client)
