# Global open data products

The local library of **open (cross-workspace) data products** — the offline
counterpart of the NextCloud `global/open_data_products/` area, mirroring the
`data/global_services/` convention. The Data Products module unions this
directory with the NextCloud source, so products here appear in the "open"
list with or without NextCloud. Override the location with
`GLOBAL_DATA_PRODUCTS_DIR`.

## Layout

One folder per product:

```
<ProductName>/
├── <ProductName>.ttl    # the product's components + attributes (dici_onto terms)
└── resources/           # optional files referenced by attributes (CSV, PDF, …)
```

## Bundled starter product

- **`MotelDB/`** — a technology reference database (heat pumps, PV, storage,
  boilers, …) with cost and efficiency attributes, each backed by a citable
  `dici_onto:Reference` (DOI). Generated from
  `data/ingestion/input/MotelDB.xlsx` via the Excel ingestion pipeline — to
  regenerate, convert that workbook (Replica Builder → Excel Import) and copy
  the result here. Don't hand-edit the TTL.
