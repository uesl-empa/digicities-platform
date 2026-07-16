# NextCloud seed content

Files here are uploaded to the local NextCloud overlay by `tutorial/start_tutorial.py`
when it detects NextCloud is configured (`NEXTCLOUD_BASE_URL` + creds set,
server reachable). The launcher skips this step silently when the stack is
running in local-fs mode.

## Layout

```
nextcloud/
├── ontology_extensions/
│   └── alpine_village_extension.ttl              → {workspace}/ontology/extensions/
├── data_products/
│   ├── building_a_electricity_demand/            → {workspace}/private_data_products/…
│   ├── pv_a_generation/                          → {workspace}/private_data_products/…
│   ├── alpine_village_map/                       → {workspace}/private_data_products/…
│   └── attribute_types_demo/                     → {workspace}/private_data_products/…
├── scenarios/
│   ├── alpine_village_baseline.ttl               → {workspace}/scenarios/
│   └── alpine_village_doubled_pv.ttl             → {workspace}/scenarios/
└── services/
    ├── alpine_village_optimisation.yaml          → {workspace}/services/
    └── alpine_village_demand_summary.yaml        → {workspace}/services/
```

Each data-product folder contains:

- `<product_name>.ttl` — the manifest the Data Products module parses.
- `resources/` — the raw data files the manifest references (CSV, GeoJSON).

## What lands where, after seeding

| NextCloud path (as `admin`) | What you'll see |
|---|---|
| `/workspace_demo/ontology/extensions/alpine_village_extension.ttl` | Concrete attribute classes (`FloorArea`, `RatedElectricalPower`, `PanelTilt`, `ImportPrice`, etc.) wired into the village's instance data. Loadable via the Ontology Manager. |
| `/workspace_demo/private_data_products/building_a_electricity_demand/` | 168-row hourly demand CSV + manifest. Renders as a line chart. |
| `/workspace_demo/private_data_products/pv_a_generation/` | 168-row PV generation CSV + manifest. |
| `/workspace_demo/private_data_products/alpine_village_map/` | 7-point GeoJSON of component locations in the Swiss Alps. Renders on a Folium map. |
| `/workspace_demo/private_data_products/attribute_types_demo/` | One component (an industrial heat pump) carrying one attribute of every shape — Physical, SimpleCost, UnitBasedCost, Dynamic, Curve, Categorical, Event, Annotation, Geospatial, CustomPhysicalRatio, Identifier. Use as a copy-paste reference. |
| `/workspace_demo/scenarios/alpine_village_baseline.ttl` | A `dici_onto:Scenario` snapshot anchoring every village component+flow via `usedInScenario`. The bare-minimum baseline pattern. |
| `/workspace_demo/scenarios/alpine_village_doubled_pv.ttl` | Variant of the baseline. Includes a `dici_onto:Assumption` describing the PV uprate from 8 → 16 kW, and a fresh `peakPower_doubled` attribute superseding the original. |
| `/workspace_demo/services/alpine_village_optimisation.yaml` | Full service-mapping example: maps the village's generators/consumers/storage/converters into a hypothetical optimiser's input shape. |
| `/workspace_demo/services/alpine_village_demand_summary.yaml` | Tiny example — just floor area + annual demand per building. Useful starter when authoring your own service. |

All content is synthetic and idempotent — re-running `start_tutorial.py` overwrites in place.
