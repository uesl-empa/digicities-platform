# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Generate the reference CSVs for data/ingestion_template/.

Run from the repo root:

    python data/ingestion_template/_build_csvs.py

Produces two files:

    data/ingestion_template/attribute_types.csv
        Every supported attribute type as a column, with three demo rows
        showcasing year/date/datetime variants of `Event`. Lay-out matches
        the 6-header-row convention the importer uses for .xlsx sheets.

    data/ingestion_template/reference.csv
        Reference sheet (citations). IDs here are the values you put in
        any `<attr>_datasource` column to attach a citation to a triple.

These are committed alongside the script so the diff stays reviewable.
Re-run only when the example values change.
"""
import csv
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Main attribute-type reference                                                #
# --------------------------------------------------------------------------- #

attribute_types_rows = [
    # Row 1 — attribute name. Column "id" is the instance-ID column.
    # `<name>_datasource` is the convention the importer uses to attach a
    # citation (see reference.csv) to the triple emitted by `<name>`.
    [
        "id", "powerRating", "annualMaintenance", "investmentCost", "assetTier",
        "yearBuilt", "locatedIn", "assetId", "label", "comment",
        "partLoadCurve", "energyPrice", "geometryFile", "tag",
        "demandHistoric", "demandLive", "demandFuture",
        "powerRating_datasource",
    ],
    # Row 2 — attribute type. One of the 15 the importer recognises.
    [
        "", "Physical", "SimpleCost", "UnitBasedCost", "Categorical",
        "Event", "ClassObject", "Identifier", "Annotation", "Annotation",
        "Curve", "CustomPhysicalRatio", "Resource", "SimpleValue",
        "Historic", "Live", "Future",
        "",
    ],
    # Row 3 — primary unit (QUDT short code). Used by Physical, UnitBasedCost,
    # Curve (x-axis), CustomPhysicalRatio (numerator), and Historic/Live/Future.
    [
        "", "KiloW", "", "KiloW", "",
        "", "", "", "", "",
        "PERCENT", "CHF", "", "",
        "KiloW-HR", "KiloW-HR", "KiloW-HR",
        "",
    ],
    # Row 4 — y-axis / denominator unit. Curve y-axis and CustomPhysicalRatio
    # denominator only.
    [
        "", "", "", "", "",
        "", "", "", "", "",
        "PERCENT", "KiloW-HR", "", "",
        "", "", "",
        "",
    ],
    # Row 5 — currency (ISO code). SimpleCost and UnitBasedCost only.
    [
        "", "", "CHF", "CHF", "",
        "", "", "", "", "",
        "", "", "", "",
        "", "", "",
        "",
    ],
    # Row 6 — predicate (dici_onto property name). ClassObject only — names
    # the dici_onto property connecting the instance to the target.
    [
        "", "", "", "", "",
        "", "locatedIn", "", "", "",
        "", "", "", "",
        "", "", "",
        "",
    ],
    # Row 7 — LinkedClassObjectType (optional). The literal string
    # "LinkedClassObjectType" anywhere in this row tells the importer to
    # switch into 7-row-header mode for the WHOLE workbook (so every other
    # sheet must have a row 7 too — see reference.csv). On a ClassObject
    # column, this row's value is a full URI prefix (must end with `/` or
    # `#`); the cell value below is concatenated onto it directly,
    # bypassing whatever `uri_mode` the converter is called with.
    [
        "LinkedClassObjectType",
        "", "", "", "",
        "", "https://example.org/locations/", "", "", "",
        "", "", "", "",
        "", "", "",
        "",
    ],
    # Data row 1 — year-precision Event. Demonstrates the simplest temporal
    # value and every other attribute type once.
    [
        "DemoYear", "12.5", "250.0", "1800.0", "Tier1Asset",
        "1985", "AlpineValley", "ASSET-001",
        "Demo (year-precision Event)",
        "Carries one example of every attribute type the importer supports.",
        "[(0.0,0.0);(50.0,80.0);(100.0,95.0)]", "0.25",
        "resources/demo.geojson", "hello",
        "resources/demand_historic.csv",
        "https://api.example.org/live/demand",
        "resources/demand_forecast.csv",
        "swiss_energy_atlas_2024",
    ],
    # Data row 2 — date-precision Event (YYYY-MM-DD). Other columns kept
    # sparse so the rows are easy to read side-by-side.
    [
        "DemoDate", "8.0", "180.0", "1500.0", "Tier2Asset",
        "2020-06-15", "AlpineValley", "ASSET-002",
        "Demo (date-precision Event)",
        "Same shape; yearBuilt parsed as xsd:date.",
        "", "0.18", "", "world",
        "", "", "",
        "",
    ],
    # Data row 3 — datetime-precision Event (ISO 8601). Timestamp parsing
    # path for hour/minute precision.
    [
        "DemoDateTime", "4.5", "120.0", "1100.0", "Tier3Asset",
        "2024-03-15T08:30:00", "AlpineValley", "ASSET-003",
        "Demo (datetime Event)",
        "yearBuilt parsed as xsd:dateTime with full timestamp.",
        "", "", "", "",
        "", "", "",
        "",
    ],
]

with (OUT_DIR / "attribute_types.csv").open("w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(attribute_types_rows)

# --------------------------------------------------------------------------- #
# Reference (citation) sheet                                                   #
# --------------------------------------------------------------------------- #

# The Reference sheet has the same 6-header-row layout as any other sheet,
# but the importer special-cases it: every row becomes a dici_onto:Reference
# instance, and the `id` value is what you put in `<attr>_datasource` cells
# elsewhere in the workbook to attach a citation to that attribute.

reference_rows = [
    ["id", "description", "ReferenceType", "URL", "AccessDate", "comment"],
    ["", "", "", "", "", ""],  # row 2 — type (Reference sheet ignores this)
    ["", "", "", "", "", ""],  # row 3 — unit
    ["", "", "", "", "", ""],  # row 4 — unit_y
    ["", "", "", "", "", ""],  # row 5 — currency
    ["", "", "", "", "", ""],  # row 6 — predicate
    # Row 7 — LinkedClassObjectType. Reference doesn't use this, but the
    # ROW must exist if any other sheet in the workbook triggers 7-row mode
    # (otherwise pandas would consume the first reference data row as a
    # header level when reading with header=[0,1,2,3,4,5,6]).
    ["LinkedClassObjectType", "", "", "", "", ""],
    [
        "swiss_energy_atlas_2024",
        "Swiss Federal Energy Atlas 2024",
        "Dataset",
        "https://www.uvek-gis.admin.ch/BFE/storymaps/EE_Energieatlas/",
        "2024-03-15",
        "Federal building-stock electricity demand database",
    ],
    [
        "ipcc_ar6_wg3_2022",
        "IPCC AR6 WG3 — Mitigation of Climate Change (2022)",
        "Publication",
        "https://www.ipcc.ch/report/ar6/wg3/",
        "2024-04-01",
        "Sector-level emission factor source for cross-checks.",
    ],
]

with (OUT_DIR / "reference.csv").open("w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(reference_rows)

print(f"wrote {OUT_DIR / 'attribute_types.csv'}")
print(f"wrote {OUT_DIR / 'reference.csv'}")
