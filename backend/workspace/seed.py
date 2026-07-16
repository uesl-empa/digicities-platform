# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Seed a workspace with content from a source directory.

Used to bootstrap NextCloud-backed (or any backend-backed) workspaces with
the bundled Alpine Village demo dataset. Maps pre-v0.2 folder names from
tutorial/sample_data/nextcloud/ to the canonical v0.2 layout so the same
seed data can populate both legacy and canonical workspaces.

Idempotent — re-running overwrites existing files. Safe to run any time.

Usage (from inside the Streamlit container, with USECASES_DIR set):

    python -m backend.workspace.seed alpine_village workspace_demo

Programmatic:

    from backend.workspace import load_registry
    from backend.workspace.seed import seed_workspace_from_alpine_village
    ctx = load_registry().by_id("workspace_demo")
    seed_workspace_from_alpine_village(ctx)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterator

from .context import WorkspaceContext


# Pre-v0.2 path → canonical-v0.2 path. Only the dirs that diverged need mapping.
LEGACY_TO_CANONICAL = {
    "ontology_extensions": "ontology/extensions",
    "data_products":       "private_data_products",
    # Identical: scenarios/, services/
}


def _iter_files(src: Path) -> Iterator[Path]:
    for p in src.rglob("*"):
        if p.is_file():
            yield p


def _remap_relative(rel: Path) -> Path:
    """Map a relative path from a pre-v0.2 seed dir to the canonical layout."""
    parts = list(rel.parts)
    if not parts:
        return rel
    first = parts[0]
    if first in LEGACY_TO_CANONICAL:
        parts[0:1] = LEGACY_TO_CANONICAL[first].split("/")
    return Path(*parts)


def upload_dir_to_workspace(
    ctx: WorkspaceContext,
    src_dir: Path,
    *,
    remap: bool = True,
    skip_filenames: tuple[str, ...] = ("README.md",),
) -> dict:
    """Upload every file under `src_dir` into the workspace's storage.

    Files keep their relative paths; if `remap=True`, top-level dir names are
    rewritten via LEGACY_TO_CANONICAL.

    Returns a summary dict with file counts and the list of uploaded paths.
    """
    if not src_dir.exists():
        raise FileNotFoundError(src_dir)

    uploaded: list[str] = []
    skipped: list[str] = []

    for fp in _iter_files(src_dir):
        if fp.name in skip_filenames:
            skipped.append(str(fp.relative_to(src_dir)))
            continue
        rel = fp.relative_to(src_dir)
        dest_rel = _remap_relative(rel) if remap else rel
        dest_str = str(dest_rel).replace("\\", "/")
        try:
            if fp.suffix.lower() in (".png", ".jpg", ".jpeg", ".geojson", ".pdf", ".zip", ".xlsx", ".xls"):
                ctx.storage.write_bytes(dest_str, fp.read_bytes())
            else:
                ctx.storage.write_text(dest_str, fp.read_text(encoding="utf-8"))
            uploaded.append(dest_str)
        except Exception as exc:
            print(f"[seed] failed {fp} → {dest_str}: {exc}")
            skipped.append(dest_str)

    return {"uploaded": uploaded, "skipped": skipped, "total": len(uploaded)}


def seed_workspace_from_alpine_village(
    ctx: WorkspaceContext,
    platform_root: Path | None = None,
) -> dict:
    """Push the bundled Alpine Village seed into the given workspace.

    Layout sources:
    - tutorial/sample_data/nextcloud/  (legacy paths, remapped to canonical)
    - tutorial/sample_data/alpine_village.ttl  → ingestion/output/

    Also writes workspace_meta/metadata.json with a sensible default if none
    exists yet.
    """
    here = Path(__file__).resolve()
    platform_root = platform_root or here.parents[2]
    seed_root = platform_root / "tutorial" / "sample_data"

    # 1. metadata.json — only if missing (don't clobber user-customised metadata)
    if not ctx.storage.exists("workspace_meta/metadata.json"):
        meta = {
            "id": ctx.id,
            "name": ctx.name or "Alpine Village (seeded)",
            "description": (
                "Fictional Swiss district seeded from the Digicities bundled "
                "tutorial. Three buildings, one PV array, one battery, one heat "
                "pump. Includes a baseline + 'doubled PV' scenario, two services, "
                "and four data products. Demonstrates the NextCloud-backed "
                "workspace path."
            ),
            "created": date.today().isoformat(),
            "tags": ["alpine-village", "demo", "tutorial", "nextcloud"],
        }
        ctx.storage.write_text("workspace_meta/metadata.json", json.dumps(meta, indent=2))

    # 2. The bundled tutorial/sample_data/nextcloud tree.
    nc_seed = seed_root / "nextcloud"
    summary = upload_dir_to_workspace(ctx, nc_seed, remap=True)

    # 3. The Alpine Village instance TTL — push to canonical ingestion/output.
    av_ttl = seed_root / "alpine_village.ttl"
    if av_ttl.exists():
        ctx.storage.write_text("ingestion/output/alpine_village.ttl", av_ttl.read_text(encoding="utf-8"))
        summary["uploaded"].append("ingestion/output/alpine_village.ttl")
        summary["total"] += 1

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import sys
    from .registry import load_registry

    if len(argv) != 3 or argv[1] != "alpine_village":
        print("usage: python -m backend.workspace.seed alpine_village <workspace_id>", file=sys.stderr)
        return 2

    workspace_id = argv[2]
    ctx = load_registry().by_id(workspace_id)
    if ctx is None:
        print(f"workspace {workspace_id!r} not found in the registry", file=sys.stderr)
        return 1

    summary = seed_workspace_from_alpine_village(ctx)
    print(f"seeded {summary['total']} files into workspace '{workspace_id}' (backend={ctx.storage_backend})")
    for path in summary["uploaded"][:5]:
        print(f"  {path}")
    if len(summary["uploaded"]) > 5:
        print(f"  ... and {len(summary['uploaded']) - 5} more")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
