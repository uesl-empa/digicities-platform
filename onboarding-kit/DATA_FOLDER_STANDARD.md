# Digicities data folder standard

Version 0.1 (draft, 2026-11-18)

A folder that meets this standard can be onboarded onto Digicities without a reader
written for it. The platform reads a short list of open formats, in a short list of
shapes. Anything else is converted into one of them first, by its owner or by a
converter that lives outside the platform.

There are two levels:

- **Level 1, required.** Every data file is in an accepted format and an accepted shape,
  and the folder has an onboarding guide. The onboarding agent maps the folder, and asks
  about what the files do not state.
- **Level 2, recommended.** The tabular data is a [Frictionless Data Package](https://datapackage.org/)
  that states what each table and column is, its unit, its missing-value words and its
  links. Nothing has to be guessed.

Check a folder before uploading it:

```bash
python -m onboarding_agent.folder_check <folder>
```

It reports, file by file, what is not yet compatible and how to fix it, and which level
the folder meets. The agent runs the same check when a folder is uploaded.

## The folder

```
<folder>/
  onboarding_guide.md     what the data is, and what the service reads and returns
  data/                   the data files
    datapackage.json      level 2: the descriptor of the tables
  run/settings.yaml       optional: the settings of a model run
```

## Accepted formats

| Format | Files | Notes |
|---|---|---|
| Delimited text | `.csv`, `.tsv` | UTF-8. One header row. The separator and decimal mark are read from the file; state them in the descriptor (`dialect`, `decimalChar`) at level 2. |
| Excel workbook | `.xlsx`, `.xlsm` | Values, not formulas: the workbook must have been saved by Excel so each formula cell holds its value. Macros are ignored. |
| JSON, YAML | `.json`, `.yaml`, `.yml` | Records in lists or mappings. |
| GeoJSON | `.geojson`, `.json` | RFC 7946: WGS84 longitude and latitude. A file in another reference system states it. |
| IFC | `.ifc` | ISO 16739 building models, IFC2x3 or IFC4, read with IfcOpenShell into one table per IFC class, with property sets, quantities and the spatial structure. |
| Text | `.md`, `.txt`, `.py` | Read as documentation and code, never as records. |

Not accepted, convert first: formats of one tool (an EPANET `.inp`, an OSeMOSYS or GAMS
data file, a model's binary save file), tables inside PDFs or images, and archives inside
the folder. Not yet accepted: NetCDF, HDF5, Parquet.

## Accepted shapes

Records, the things the data is about:

| | Shape | Example |
|---|---|---|
| R1 | One row per thing, one column per attribute | a table of buildings |
| R2 | Records at a path in a JSON or YAML file | `turbines: [...]` |
| R3 | Map features: properties and a geometry | a GeoJSON of trees |
| R4 | Several tables on one sheet, side by side or one under another, separated by empty columns or rows; a title cell above a table names it | lists of technologies, fuels and emissions |
| R5 | One row per thing and attribute, a column naming the attribute | `Parameter, Technology, Value` |
| R6 | A building model (IFC): storeys, spaces, elements and how they relate | an architect's model |

Series, values over time:

| | Shape | Example |
|---|---|---|
| S1 | A file per series, named in a cell of the thing it belongs to | `profiles/demand.csv` |
| S2 | Long: one row per thing and time step, with a column for the time | `point, time, count` |
| S3 | Wide: one time column, one column per thing, headed by the thing's id | `time, n54, n57` |
| S4 | One row per thing, one column per year or date | `Technology, 2025, 2030, 2035` |

## Values

- One value per cell. A unit written in the cell (`890 CHF/kW`) is read only when every
  cell of the column is written the same way.
- Numbers are numbers: no thousands separators, one decimal mark per file.
- A missing value is an empty cell. If the source writes a word for it (`n/a`, `unknown`),
  state the word: in the guide at level 1, in `missingValues` at level 2.
- Dates and times are ISO 8601 (`2025-08-25T14:00:00+02:00`). A time without an offset
  is read as local time of an unstated zone: state the zone.
- Codes (a type, a status) are listed with their meaning: in the guide, or as `categories`
  in the descriptor.
- Coordinates state their reference system, unless they are GeoJSON's WGS84.

## Level 2: the descriptor

A Frictionless tabular data package, `data/datapackage.json`, with these Digicities
properties added. They are ordinary extra properties: any Frictionless tool still reads
the package.

| Where | Property | Says |
|---|---|---|
| package | `licenses`, `sources` | the licence and where the data comes from (required) |
| package | `timezone` | the IANA time zone (`Europe/Zurich`) of times written without an offset |
| resource | `rdfType` | the class of its rows, a Digicities ontology IRI |
| field | `rdfType` | the attribute or link the column is, an ontology IRI |
| field | `unit` | the QUDT unit code of a quantity (`KiloW`, `M3-PER-HR`) |
| field | `currency` | the ISO 4217 code of a cost (`CHF`) |
| field | `profile` | `true` when the cell names a series file (shape S1) |
| field | `refersTo` | the resources a link may point into, when more than one |
| schema | `primaryKey` | the id column |
| schema | `foreignKeys` | links into one other resource |
| schema | `missingValues` | the words the source writes for "unknown" |
| resource | `dialect` | `delimiter`, when not a comma |
| field | `decimalChar` | the decimal mark, when not a point |

```json
{
  "name": "district-heat",
  "profile": "tabular-data-package",
  "licenses": [{"name": "CC-BY-4.0"}],
  "sources": [{"title": "City of Example, open data portal"}],
  "resources": [{
    "name": "substations",
    "path": "substations.csv",
    "profile": "tabular-data-resource",
    "rdfType": "https://digicities.info/ontology#EnergyConverter",
    "schema": {
      "primaryKey": "id",
      "missingValues": ["", "unknown"],
      "fields": [
        {"name": "id", "type": "string"},
        {"name": "name", "type": "string",
         "rdfType": "http://www.w3.org/2000/01/rdf-schema#label"},
        {"name": "capacity", "type": "number", "unit": "KiloW",
         "rdfType": "https://digicities.info/ontology#FlowCapacity"},
        {"name": "heat_out", "type": "string", "profile": true, "unit": "KiloW",
         "rdfType": "https://digicities.info/ontology#FlowRate"}
      ]
    }
  }]
}
```

## Converting other formats

A converter reads one tool's or one sector's format and writes a folder that meets this
standard, ideally level 2. It lives outside the platform, with the tool or with the data's
owner, so the platform never grows a reader per tool. Its output is checked like any other
folder.
