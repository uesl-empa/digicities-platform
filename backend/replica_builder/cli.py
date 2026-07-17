# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""CLI for the Replica Builder's Excel-to-TTL conversion.

Lets partners convert a filled-in Digicities ingestion workbook to TTL without
opening the Streamlit UI. Designed to run inside the platform's Streamlit
container so the only dependency on the partner's side is Docker:

    docker exec digicities-streamlit \\
        python -m backend.replica_builder.cli \\
        /app/data/usecases/<workspace>/ingestion/input/<your_workbook>.xlsx

The TTL lands next to the input by default at
`<workspace>/ingestion/output/<your_workbook>.ttl`. Pass `-o/--output` to
override the output path, `--project-uri` to override the auto-derived URI,
or `--uri-mode` to switch URI-construction strategy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.replica_builder.utils.create_class_and_attribute_graph import (
    process_excel_to_ttl,
)

DEFAULT_PROJECT_URI_PREFIX = "https://digicities.info/proj"


def derive_project_uri(xlsx_path: Path) -> str:
    """Derive a sensible project URI from the workbook filename.

    `my_workbook.xlsx` -> `https://digicities.info/proj/my_workbook`
    """
    stem = xlsx_path.stem
    return f"{DEFAULT_PROJECT_URI_PREFIX}/{stem}"


def derive_output_path(xlsx_path: Path) -> Path:
    """Workbook in `<workspace>/ingestion/input/foo.xlsx`
    -> TTL at `<workspace>/ingestion/output/foo.ttl`. If the workbook isn't under
    `ingestion/input/`, drop the TTL next to the workbook instead.
    """
    if xlsx_path.parent.name == "input" and xlsx_path.parent.parent.name == "ingestion":
        output_dir = xlsx_path.parent.parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{xlsx_path.stem}.ttl"
    return xlsx_path.with_suffix(".ttl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.replica_builder.cli",
        description="Convert a filled-in Digicities Excel ingestion workbook to TTL.",
    )
    parser.add_argument(
        "xlsx",
        type=Path,
        help="Path to the filled-in workbook (.xlsx). Inside the container this is "
             "typically /app/data/usecases/<workspace>/ingestion/input/<name>.xlsx.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <workspace>/ingestion/output/<name>.ttl "
             "when the input sits under <workspace>/ingestion/input/, otherwise "
             "alongside the workbook.",
    )
    parser.add_argument(
        "--project-uri",
        default=None,
        help=f"Project URI to embed in the TTL. Defaults to "
             f"{DEFAULT_PROJECT_URI_PREFIX}/<workbook-stem>.",
    )
    parser.add_argument(
        "--uri-mode",
        choices=("default", "full-uri-in-cell", "complete-project-uri"),
        default="default",
        help="URI-construction strategy passed to process_excel_to_ttl. See the "
             "ingestion template docs for what each mode does.",
    )
    parser.add_argument(
        "--ontology-dir",
        type=Path,
        default=None,
        help="Workspace ontology directory (with extensions/ + vendored core). When "
             "given, any Physical/Geospatial attribute the workbook leaves without a "
             "unit is stamped with its class's dici_onto:hasDefaultUnit.",
    )
    args = parser.parse_args(argv)

    if not args.xlsx.exists():
        parser.error(f"workbook not found: {args.xlsx}")
    if args.xlsx.suffix.lower() != ".xlsx":
        parser.error(f"expected .xlsx, got {args.xlsx.suffix}")

    project_uri = args.project_uri or derive_project_uri(args.xlsx)
    output_path = args.output or derive_output_path(args.xlsx)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[ingest] workbook    : {args.xlsx}")
    print(f"[ingest] project URI : {project_uri}")
    print(f"[ingest] uri mode    : {args.uri_mode}")
    print(f"[ingest] output      : {output_path}")

    default_units = None
    if args.ontology_dir:
        from backend.replica_builder.utils.default_units import load_workspace_default_units
        default_units = load_workspace_default_units(ontology_dir=str(args.ontology_dir))
        print(f"[ingest] default units: {len(default_units)} class(es) from {args.ontology_dir}")

    process_excel_to_ttl(
        project_uri=project_uri,
        file_path=str(args.xlsx),
        output_ttl_path=str(output_path),
        uri_mode=args.uri_mode,
        default_units=default_units,
    )

    if not output_path.exists():
        print(f"[ingest] FAILED — no TTL written at {output_path}", file=sys.stderr)
        return 1

    size_kb = output_path.stat().st_size / 1024
    print(f"[ingest] wrote {size_kb:.1f} KB to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
