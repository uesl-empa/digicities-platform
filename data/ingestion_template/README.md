# Ingestion template, working folder

This is the working directory for real-project Replica Builder Excel ingestion. Drop your validated `.xlsx` workbook here, run the conversion, and the resulting `.ttl` lands next to it. Both `.xlsx` and `.ttl` files in this folder are git-ignored. Your project data stays local.

## What's in here

| File | Tracked? | Purpose |
|---|---|---|
| `attribute_types.csv` | yes | Reference sheet showing **every supported attribute type** with the cells the importer reads for each one. Copy values from here into your validated Excel workbook. |
| `reference.csv` | yes | Example structure for the `Reference` sheet (citations). IDs here become the values you put in `<attr>_datasource` columns to attach a `prov:wasDerivedFrom` link. |
| `_build_csvs.py` | yes | Generator for the two CSVs above. Re-run only when the example values need updating. |
| `*.xlsx` | **ignored** | Your project workbook(s). Excel data-validation rules stay intact; the CSV is reference-only. |
| `*.ttl` | **ignored** | Conversion outputs. Generated next to the source `.xlsx`. |

## Why CSV instead of an Excel reference

If the example data shipped as Excel, copying it into your validated workbook would risk overwriting the dropdown and list-validation rules on those cells. A CSV is plain text. Paste **values only** into your Excel cells and the validation stays untouched.

## How the CSVs map to the Excel template

Both CSVs follow the importer's **7-row** header convention. Each row is one Excel row:

| CSV row | Excel header | What it carries |
|---|---|---|
| 1 | Attribute name | Becomes `dici_onto:<name>` for the attribute. Column `id` flags the instance-ID column. |
| 2 | Attribute type | One of `Physical`, `SimpleCost`, `UnitBasedCost`, `Categorical`, `Event`, `ClassObject`, `Identifier`, `Annotation`, `Curve`, `CustomPhysicalRatio`, `Resource`, `SimpleValue`, `Historic`, `Live`, `Future`. |
| 3 | Unit (or x-axis unit) | QUDT short code (`KiloW`, `M2`, `KiloW-HR`, `PERCENT`). |
| 4 | y-axis / denominator unit | Curve y-axis or `CustomPhysicalRatio` denominator only. |
| 5 | Currency | ISO code for `SimpleCost` / `UnitBasedCost`. |
| 6 | Predicate | `dici_onto:` property name for `ClassObject` (e.g. `locatedIn`, `installedAt`). |
| 7 | **LinkedClassObjectType** *(optional)* | `ClassObject` only. A full URI prefix (must end with `/` or `#`) that gets prepended to the cell value, **overriding** whatever `uri_mode` the converter is called with. The literal string `LinkedClassObjectType` in the `id` column flips the importer into 7-row mode for the **whole workbook**. |
| 8+ | Instance rows | Each row is one component instance. |

`attribute_types.csv` has three demo rows so you can see the year-only, full-date, and full-timestamp variants of `Event` side-by-side. The other types use one example each. Copy the cell values into the corresponding columns of your validated template.

### About row 7 (LinkedClassObjectType)

This row is optional. If you don't need it, leave the literal `LinkedClassObjectType` marker out of every sheet and the importer reads only 6 header rows (data starts at row 7).

If you *do* want it on any column, it must be present on **every sheet**, even if every cell on that sheet's row 7 is blank apart from the marker. Otherwise pandas' multi-row header reader will consume the first instance row of the sheets that don't have it as a phantom header level. The bundled `reference.csv` shows the minimal "marker only" layout for sheets that don't actually use the override.

## Choosing the right attribute type

Pick the type that matches the **kind of fact** you're recording, not just the data format. The 15 types group naturally by what they describe.

### Quantities with a physical unit

- **`Physical`**: a measured or design value with a single QUDT unit. Use for any number you'd write with a unit symbol: rated power (`50 KiloW`), floor area (`120 M2`), efficiency (`92 PERCENT`), capacity (`200 KiloW-HR`). Becomes `a dici_onto:PhysicalAttribute` with `qudt:value` and `qudt:unit`. The most common type. Pick it first if you're recording "how much" or "how big".
- **`CustomPhysicalRatio`**: a ratio between two units that QUDT doesn't bundle as a single IRI: energy intensity (`KiloW-HR/M2`), CO₂ factor (`KILO-GM/KiloW-HR`), emissions per km (`KILO-GM/KiloM`). The numerator unit goes in row 3 and the denominator in row 4; together they're written as a `hasUnitLabel` string. Reach for this whenever `Physical` can't express the unit as one symbol.

### Money

- **`SimpleCost`**: a one-shot or recurring figure in a currency: `1800 CHF` investment cost, `250 CHF/year` maintenance. Currency goes in row 5; write the ISO 4217 code (`CHF`, `EUR`, `USD`, ...) and the converter emits it as a QUDT currency IRI (`cur:<CODE>` resolves to `http://qudt.org/vocab/currency/<CODE>`). No physical unit.
- **`UnitBasedCost`**: a cost expressed per unit of physical quantity: `120 CHF/KiloW` installed-power tariff, `0.18 CHF/KiloW-HR` energy price. Combines a QUDT currency (row 5, written as the ISO 4217 code, emitted as `cur:<CODE>`) with a QUDT denominator unit (row 3). Use whenever the price scales with size or throughput.

### Labels, categories, and identifiers

- **`Categorical`**: pick-from-a-fixed-set tags: tier (`Tier1Asset`, `Tier2Asset`), operational state (`Operational`, `Decommissioned`), technology family (`HeatPumpAirSource`). The cell value must be a class name that exists in the core ontology or your extension. It's emitted as `?inst a dici_onto:<value>`. Use this for closed vocabularies. *Not* for free-form text and *not* for IDs.
- **`Annotation`**: free-form human-readable text: a label, a comment, a note, a URL for further reading. If the column name is one of `label`, `comment`, `seeAlso`, or `isDefinedBy` it's emitted as `rdfs:<name>` (the standard RDF annotation properties). Anything else lands under your project namespace as `:<column_name>`. Reserve for prose. If your values come from a closed list (e.g. `BaseCarrier` with values `Electricity` / `Heat` / `Gas`), use `Categorical` instead so they become typed.
- **`Identifier`**: an opaque string key from an external system: an asset tag like `ASSET-001`, an SAP equipment number, a registry code. Attached via `dici_onto:hasIdentifier` so multiple external systems can each carry their own key for the same component without collision. Not for display names (use `label` annotation) or category tags (use `Categorical`).

### Relationships and events

- **`ClassObject`**: points one instance at another instance. "Located in", "connected to", "installed at", "supplies", "is downstream of". The relating predicate goes in row 6. For example, a building's `locatedIn` cell value `AlpineValley` becomes `<…/Building/A> dici_onto:locatedIn <…/Location/AlpineValley>`. The optional 7th row (`LinkedClassObjectType`) overrides the target's namespace, useful for pointing at instances in a different vocabulary or in another partner's workspace. Use whenever the value is the *name of another thing in the model*, not a quantity.
- **`Event`**: a point in time: year built, decommissioning date, when a reading was taken. Precision is auto-detected from the cell value: `1985` becomes `xsd:gYear`, `07.1970` becomes `xsd:gYearMonth`, `2020-06-15` becomes `xsd:date`, `2024-03-15T08:30:00` becomes `xsd:dateTime`. Match the precision to what you actually know. If you only have a year, write a year. Don't fake a day.

### Curves, files, and time-series

- **`Curve`**: a list of `(x, y)` points: part-load efficiency vs load, COP vs source temperature, cost vs installed capacity. Cell value is a string `[(x1,y1);(x2,y2);…]`. Both axes carry units (x in row 3, y in row 4). **Format the cell as Text first** in Excel. Otherwise it tries to parse the parentheses as a formula.
- **`Resource`**: a relative path inside the workspace pointing at a bundled file: `resources/floorplan.geojson`, `private_data_products/grid/topology.svg`. The platform resolves the path at access time. Use for geometry, blueprints, schematics, raw measurement dumps, anything too big or unstructured for a cell.
- **`Historic`**: a pointer to a historical time-series CSV (e.g. measured demand for 2023). Cell value is a relative path: `resources/demand_2023.csv`. Adds a `dici_onto:hasHistoricTimeSeries` link from the parent attribute to a typed `TimeSeries` resource, with the column's unit attached to the time-series too.
- **`Live`**: a real-time data source URL: `https://api.example.org/live/demand`. Emitted under `dici_onto:hasLiveTimeSeries`. The platform treats it as a polling endpoint rather than a file. Use for SCADA feeds, smart-meter APIs, weather services.
- **`Future`**: a pointer to a forecast or projected time-series CSV: `resources/demand_2030.csv`. Same shape as `Historic` but under `dici_onto:hasFutureTimeSeries`. Use one or all three (`Historic` / `Live` / `Future`) depending on what your usecase actually has.

### Catch-all

- **`SimpleValue`**: a bare value (decimal or string) with no unit, currency, or category meaning: a free-form numeric tag, a unitless ratio someone wrote down as a number. Reach for it only after `Physical`, `Categorical`, `Annotation`, and `Identifier` don't fit. Those four cover most "unitless" cases more meaningfully.

### Quick decision flow

1. **Does the value have a physical unit?** Use `Physical`. Or `Curve` if it's a function. Or `CustomPhysicalRatio` if the unit is a ratio QUDT can't express as one symbol.
2. **Is the value money?** Use `SimpleCost` (one-off or annual) or `UnitBasedCost` (per kW, per kWh, ...).
3. **Is the value the name of another thing in the model?** Use `ClassObject`.
4. **Is the value a timestamp?** Use `Event`.
5. **Is the value a file path or URL?** Use `Resource` (static file), `Historic` or `Future` (time-series CSV), or `Live` (real-time URL).
6. **Is the value a label, note, or external ID?** Use `Annotation` (prose), `Identifier` (opaque key), or `Categorical` (closed vocabulary).
7. **None of the above?** Use `SimpleValue`. But pause first. Usually one of the above is a better fit.

### Tricky types, quick reference

- **`Curve`**: format the cell as Text first. Excel will mangle the parentheses otherwise.
- **`Event`**: let the precision match what you know. `1985` is fine. Don't pad it to `1985-01-01`.
- **`ClassObject` under `default` URI mode**: the cell value is concatenated as `<{project_uri}/{value}>`. Use `Sheet/instanceId` (e.g. `Location/AlpineValley`) to point at instances on other sheets. With row 7's **LinkedClassObjectType**, the cell value is appended verbatim to the row-7 prefix, useful for cross-namespace links.
- **`<attr>_datasource`**: a sibling column that attaches a citation to the triple emitted by `<attr>`. If the cell value matches an `id` in your `Reference` sheet, it becomes `prov:wasDerivedFrom <…/Reference/<id>>`. Otherwise it's stored verbatim as `dcterms:source`. Works for `Physical`, `SimpleCost`, `UnitBasedCost`, `Event`, `Curve`, `SimpleValue`, `CustomPhysicalRatio`.

## End-to-end workflow

1. Open `attribute_types.csv` in any text editor or spreadsheet tool. Open it as **read-only** if your tool will otherwise auto-format the curve cell.
2. In your validated Excel template, decide which attribute type each column should be.
3. Copy the **values only** from the matching CSV cells into the matching Excel header rows. Excel's validation rules stay intact because you're pasting values, not pasting cells.
4. Fill in your own instance rows below row 6.
5. Save your workbook in this folder. It'll be git-ignored automatically.
6. Run the conversion. Two options:

   **A. Notebook 09's BYO section.** Open `tutorial/09_excel_import.ipynb`, section *9.10 Bring your own template*. Edit the `USER_DIR` line to point at this folder:

   ```python
   USER_DIR = pathlib.Path('../data/ingestion_template').resolve()
   ```

   Then run the cells beneath. The dropdown picks up your `.xlsx`. The converted `.ttl` writes back to this folder.

   **B. Streamlit UI.** Use `Replica Builder → Excel Import (Legacy)` tab. Drag your workbook into the upload widget. Same `process_excel_to_ttl` function under the hood.

The full reference (every header row, every attribute type) is in [`tutorial/09_excel_import.ipynb`](../../tutorial/09_excel_import.ipynb), sections 9.3 and 9.4.
