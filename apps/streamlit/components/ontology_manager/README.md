# Ontology Manager Module

Streamlit UI for managing the Digicities ontology — components, attributes, object properties, and mappings.

## Architecture

Runs in **integrated mode only**: direct triplestore access (Apache Jena Fuseki by default; GraphDB via the opt-in overlay) + local/NextCloud file storage. (Prior versions also supported an HTTP "API mode" talking to a Flask backend; that mode was removed in the open source release.)

## File Layout

```
components/ontology_manager/
├── __init__.py          # Streamlit entry point + module UI
├── api_client.py        # OntologyAPIClient — Streamlit-aware wrapper over backend
├── displays.py          # Display components and tables
├── forms.py             # Form handlers
└── README.md

backend/ontology_manager/
├── __init__.py          # OntologyFunctions, create_ontology_functions
└── functions/
    ├── base.py          # OntologyBase — file ops, NextCloud/local paths
    ├── component_ops.py # Component CRUD + hierarchy
    ├── attribute_ops.py # Attribute CRUD, linking, categories
    └── mapping_ops.py   # Mapping ops + triplestore uploads
```

Pure Python logic lives in `backend/ontology_manager/`. The Streamlit UI shell in `components/` wraps it with error toasts and session state.

## Storage

- **Global (read-only):** `global/ontology/` — core ontology + imports
- **Workspace (editable):** `<workspace>/ontology/` — extensions, exports, mappings, temp

## Usage

```python
from components.ontology_manager import ontology_manager_module

ontology_manager_module(workspace)  # workspace dict or GraphDB client
```
