# Workspace layout, canonical specification

A **workspace** is a folder with a defined structure that the Digicities platform reads and writes. A workspace can be backed by:

- The local filesystem (a regular directory, often a git-tracked usecase repo).
- NextCloud (a top-level folder under a NextCloud user account).
- Any other backend supported by [`fsspec`](https://filesystem-spec.readthedocs.io/) (S3, GCS, FTP, ...) in principle. Only local and NextCloud are exercised today.

Whichever backend a workspace uses, the **subfolder layout below is identical**. This makes a workspace portable. Snapshot it as a git repo, sync it to NextCloud, and back, without any platform-side adapter code.

This is the v0.2 contract. Earlier versions diverged between NextCloud and local-filesystem layouts. That divergence is gone.

> ℹ️ **Note on the `motel-energy` examples below.** Throughout this document `motel-energy` refers to the small **demo workspace** describing three fictional motels. It's a worked example used to illustrate the workspace layout. It is unrelated to `MotelDB.xlsx`, which is a separate *technology database* (an equipment-spec catalogue, not a usecase).

## Folder structure

```
<workspace-root>/
├── ontology/
│   ├── extensions/          # extension TTLs authored by this workspace
│   ├── exports/             # merged ontology exports (core + extensions)
│   ├── temp/                # editor scratch files (Ontology Manager working state)
│   └── mappings/
│       ├── input/           # mapping-rule input TTLs
│       └── output/          # mapping-rule generated outputs
├── ingestion/
│   ├── input/               # source Excel workbooks (.xlsx)
│   └── output/              # converted TTL files
├── scenarios/               # scenario TTLs (one per scenario)
├── services/                # service YAML definitions
├── queries/                 # SPARQL templates (one per .rq file)
├── private_data_products/   # data product manifests + bundled resources
│   └── <product_name>/
│       ├── <product_name>.ttl
│       └── resources/       # CSVs, GeoJSON, etc. referenced by the manifest
├── timeseries/              # CSV time-series files referenced by attributes
├── notebooks/               # analysis notebooks (Jupyter)
├── docs/                    # workspace documentation (about.md, etc.)
└── workspace_meta/          # workspace name, description, thumbnail image
    ├── metadata.json
    └── image.{png,jpg}      # optional thumbnail
```

Every subfolder above is **always present**, even if empty. The platform may auto-create missing folders on first access. Empty folders may contain a `.gitkeep`.

## Why these folders, in this shape

- **`ontology/`**: schema is conceptually one thing. Grouping its subdirs reflects that.
- **`ingestion/`**: separates "raw input" (Excel) from "ontology-typed output" (TTL). The output is the canonical, queryable form. The input is the human-edited source.
- **`scenarios/`, `services/`, `queries/`**: three flat dirs, one file per item. No subdirectories, to keep navigation simple.
- **`private_data_products/`**: each data product is a folder so its manifest and resources stay together. "Private" distinguishes from `global/open_data_products/` on NextCloud (publicly shared).
- **`timeseries/`**: large CSVs that data products reference. Separated so the data-product folder itself stays small.
- **`workspace_meta/`**: anything that's *about* the workspace rather than *in* it.

## Required vs optional

| Folder | Required at workspace creation? |
|---|---|
| `ontology/extensions/` | Yes (may be empty) |
| `ontology/exports/`, `ontology/temp/`, `ontology/mappings/{input,output}/` | Yes (may be empty) |
| `ingestion/{input,output}/` | Yes (may be empty) |
| `scenarios/`, `services/`, `queries/` | Yes (may be empty) |
| `private_data_products/` | Yes (may be empty) |
| `timeseries/` | Yes (may be empty) |
| `notebooks/` | Optional (recommended) |
| `docs/` | Optional (recommended) |
| `workspace_meta/` | Optional |

The Digicities platform's local-mode bootstrap (`services/graphdb/init.sh` and the workspace-discovery code) treats any folder with a populated `ontology/extensions/`, `ingestion/output/`, or `scenarios/` as a valid workspace.

## Workspace-meta convention

`workspace_meta/metadata.json`:

```json
{
  "id": "motel-energy",
  "name": "Roadside Motel Chain",
  "description": "Three-site motel energy modelling, demo usecase.",
  "created": "2026-05-25",
  "tags": ["buildings", "pv", "demo"]
}
```

`workspace_meta/image.png` (or `.jpg`): optional thumbnail rendered in the workspace switcher. About 400 by 300 px.

## Backends honouring this layout

### Local filesystem

Any path on disk. The workspace registry entry looks like:

```yaml
- id: motel-energy
  name: Roadside Motel Chain
  backend: local
  path: /home/you/digicities-opensource/usecases/motel-energy
```

Inside that path, the folders above are present.

### NextCloud

A top-level folder on the NextCloud user's account, named by the workspace id. The registry entry looks like:

```yaml
- id: motel-energy
  name: Roadside Motel Chain
  backend: nextcloud
  nextcloud_root: motel-energy
```

The platform's `WorkspaceStorage` adapter joins the root with the canonical subpaths (`motel-energy/ontology/extensions/...` etc.) and uses `fsspec`'s `webdav` filesystem under the hood.

### Other (S3, GCS, FTP, ...)

`fsspec` supports many backends. A workspace registry entry can in principle point at any of them:

```yaml
- id: motel-energy
  name: Roadside Motel Chain
  backend: fsspec
  protocol: s3
  root: my-bucket/digicities-workspaces/motel-energy
```

Not exercised in v0.2. Local and NextCloud are the only tested paths. The abstraction admits it for free.

## Portability flows

The point of one canonical layout is that a workspace can move between backends with a directory copy:

- **NextCloud to git repo**: `rclone copy nextcloud:motel-energy /usecases/motel-energy && cd /usecases/motel-energy && git init && git add . && git commit -m "Snapshot from NextCloud"`.
- **Git repo to NextCloud**: `git clone <repo> /tmp/motel-energy && rclone copy /tmp/motel-energy nextcloud:motel-energy`.
- **Platform-mediated**: the platform offers a *Sync to git folder* / *Sync from git folder* button (deferred to v0.3) that does the equivalent through the storage abstraction.

## Migration from pre-v0.2 layouts

Pre-v0.2 the usecase template used `extensions/` (no `ontology/` prefix), `ingestion/`, `queries/` at the top level. v0.2 nests extensions under `ontology/extensions/`. The platform's workspace loader will continue to recognise the old `extensions/` path for one release as a compatibility shim, with a warning. Tutorial seed (`tutorial/sample_data/nextcloud/`) and the usecase-template repo are migrated in this release.
