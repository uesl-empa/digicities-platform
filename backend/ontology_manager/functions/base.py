# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Ontology Manager Base Functions.

Storage model
-------------
All *editable* workspace ontology files — extensions, exports, temp, mappings,
and the active-extension marker — go through the one workspace storage
abstraction (`WorkspaceStorage`, reached via `ctx.storage`), exactly like every
other module's file I/O. That single abstraction already handles local disk,
NextCloud (WebDAV) and any other fsspec backend, so this class no longer carries
its own local-vs-NextCloud branching.

The *core* ontology and its imports (`dici_onto_core.ttl`, `imports/`) are
global, read-only platform assets — they ship vendored with the platform, not in
a workspace — so they are read directly from the vendored ontology dir, never
through workspace storage.

Editing the core ontology is only offered on local (`file`) workspaces, matching
the previous behaviour where NextCloud workspaces treated the global core as
read-only.
"""

import os
import json
import rdflib
from rdflib import Namespace
from pathlib import Path
from typing import Optional, Tuple, Any, Dict, List
from importlib.resources import files

from backend.workspace.storage import WorkspaceStorage

# Define the dici_onto namespace
dici_onto = Namespace("https://digicities.info/ontology#")


class OntologyBase:
    """Base class for ontology management, backed by a WorkspaceStorage."""

    def __init__(self,
                 storage: Optional[WorkspaceStorage] = None,
                 workspace_id: Optional[str] = None,
                 graphdb_client=None,
                 ontology_dir: Optional[str] = None,
                 # Back-compat: older callers passed NextCloud clients. They are
                 # ignored now — storage handles every backend. Kept so existing
                 # call sites don't break during migration.
                 nextcloud_client=None,
                 nextcloud_global_client=None):
        """
        Args:
            storage: WorkspaceStorage for the active workspace (preferred). When
                omitted, a local WorkspaceStorage is derived from ``ontology_dir``
                or ``workspace_id`` so non-UI callers still work.
            workspace_id: Active workspace id (used for the local fallback and
                for info/reporting).
            graphdb_client: UnifiedGraphDBClient for GraphDB upload operations.
            ontology_dir: Local ``.../ontology`` directory — used only to derive
                a local storage root when ``storage`` isn't provided.
        """
        self.workspace_id = workspace_id
        self.graphdb_client = graphdb_client

        # Core + imports are global, vendored, read-only — resolved once here.
        global_dir = self._resolve_global_ontology_dir()
        self.CORE_ONTOLOGY_FILE = os.path.join(global_dir, "dici_onto_core.ttl")
        self.IMPORTS_PATH = os.path.join(global_dir, "imports")

        # The one storage handle for all editable workspace files.
        self.storage = storage or self._build_local_storage(
            workspace_id, ontology_dir, global_dir
        )

        # Workspace-relative paths under the canonical ``ontology/`` layout.
        # These resolve identically on local disk and NextCloud via storage.
        self.WORKSPACE_ONTOLOGY_ROOT = "ontology"
        self.EXTENSION_PATH = "ontology/extensions"
        self.EXPORTS_PATH = "ontology/exports"
        self.TEMP_PATH = "ontology/temp"
        self.MAPPING_INPUT_PATH = "ontology/mappings/input"
        self.MAPPING_OUTPUT_PATH = "ontology/mappings/output"

        # Core editing is only meaningful on a local file workspace (the vendored
        # core is shared platform state); remote workspaces treat it read-only.
        self.core_readonly = self.storage.protocol != "file"
        # Back-compat alias for any external code still reading this flag.
        self.use_nextcloud = self.core_readonly

        self._ensure_workspace_structure()
        print(f"✅ OntologyFunctions initialized "
              f"(storage protocol={self.storage.protocol!r}, workspace={workspace_id})")

    # =================== Storage helpers ===================

    def _ensure_workspace_structure(self) -> None:
        """Create the editable ontology subfolders if missing (idempotent)."""
        for rel in (self.EXTENSION_PATH, self.EXPORTS_PATH, self.TEMP_PATH,
                    self.MAPPING_INPUT_PATH, self.MAPPING_OUTPUT_PATH):
            try:
                self.storage.mkdir(rel, exist_ok=True)
            except Exception as e:
                print(f"⚠️ Could not ensure {rel}: {e}")

    def _read_text(self, rel_path: str) -> Optional[str]:
        """Return file text, or None if it doesn't exist / can't be read."""
        try:
            if not self.storage.exists(rel_path):
                return None
            return self.storage.read_text(rel_path)
        except Exception as e:
            print(f"⚠️ Could not read {rel_path}: {e}")
            return None

    def _write_text(self, rel_path: str, content: str) -> None:
        self.storage.write_text(rel_path, content)

    def _list_ttl(self, rel_dir: str) -> List[str]:
        """Return the basenames of every .ttl file directly under rel_dir."""
        try:
            return sorted(p.split("/")[-1] for p in self.storage.glob(f"{rel_dir}/*.ttl"))
        except Exception as e:
            print(f"⚠️ Could not list {rel_dir}: {e}")
            return []

    def _read_graph(self, rel_path: str) -> rdflib.Graph:
        """Parse a workspace TTL file into a graph (empty graph if missing)."""
        g = rdflib.Graph()
        content = self._read_text(rel_path)
        if content:
            g.parse(data=content, format="ttl")
        return g

    def _write_graph(self, rel_path: str, g: rdflib.Graph) -> None:
        g.bind("dici_onto", dici_onto)
        self._write_text(rel_path, g.serialize(format="ttl"))

    # =================== Path resolution (global + local fallback) ===========

    @staticmethod
    def _resolve_global_ontology_dir() -> str:
        """Locate the platform's vendored ontology dir (core + imports live here).

        Never workspace-scoped. Resolution: ``ONTOLOGY_DIR`` env var, then legacy
        ``modular_dt_framework.ontologies.dici_onto`` package, then the vendored
        ``<repo_root>/data/ontology`` fallback.
        """
        env_dir = os.environ.get("ONTOLOGY_DIR")
        if env_dir:
            return env_dir
        try:
            return str(files("modular_dt_framework.ontologies.dici_onto"))
        except (ModuleNotFoundError, TypeError, ValueError):
            pass
        repo_root = Path(__file__).resolve().parents[3]
        return str(repo_root / "data" / "ontology")

    @staticmethod
    def _build_local_storage(workspace_id: Optional[str],
                             ontology_dir: Optional[str],
                             global_dir: str) -> WorkspaceStorage:
        """Build a local WorkspaceStorage rooted at the workspace root.

        Editable paths are ``ontology/...`` relative to this root, so the root is
        the workspace folder (the parent of the ``ontology/`` dir). Used only when
        no storage handle was supplied (non-UI callers).
        """
        if ontology_dir:
            # ontology_dir is the workspace's ``.../ontology`` dir → root at parent.
            return WorkspaceStorage.local(str(Path(ontology_dir).parent))
        usecases_dir = os.environ.get("USECASES_DIR")
        if workspace_id and usecases_dir:
            wr = Path(usecases_dir) / workspace_id
            if wr.exists():
                return WorkspaceStorage.local(str(wr))
        # Last resort: parent of the vendored ontology dir so ``ontology/*``
        # resolves back onto the vendored tree (mirrors the old global fallback).
        gp = Path(global_dir)
        root = gp.parent if gp.name == "ontology" else gp
        return WorkspaceStorage.local(str(root))

    # =================== Core File Operations ===================

    def load_core_ontology(self) -> rdflib.Graph:
        """Load the core ontology TTL from the vendored platform copy."""
        g = rdflib.Graph()
        local_core = getattr(self, "CORE_ONTOLOGY_FILE", None)
        if not local_core or not os.path.exists(local_core):
            local_core = os.path.join(self._resolve_global_ontology_dir(), "dici_onto_core.ttl")
        g.parse(Path(local_core).as_uri(), format="ttl")
        print(f"✅ Core ontology loaded from vendored copy: {local_core}")
        return g

    def list_extension_files(self) -> List[str]:
        """List all .ttl files in the workspace extensions folder, plus the
        core-ontology view entry."""
        files_ = self._list_ttl(self.EXTENSION_PATH)
        # Offer the core ontology for viewing (and, on local workspaces, editing).
        files_.append("CORE_ONTOLOGY_MODIFICATION")
        return files_

    def create_new_extension(self, extension_name: str) -> Tuple[bool, str]:
        """Create a new empty extension file."""
        try:
            extension_name = extension_name.strip()
            if not extension_name:
                return False, "Extension name cannot be empty"

            extension_filename = extension_name if extension_name.endswith(".ttl") else f"{extension_name}.ttl"

            template_content = f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dici_onto: <https://digicities.info/ontology#> .

# {extension_name} Extension
# Created: {self._get_timestamp()}

# Add your components, attributes, and properties below
"""
            self._write_text(f"{self.EXTENSION_PATH}/{extension_filename}", template_content)
            print(f"✅ Extension created: {extension_filename}")
            return True, f"Extension '{extension_filename}' created successfully"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"Error creating extension: {str(e)}"

    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def load_extension(self, extension_filename: str) -> rdflib.Graph:
        """Load the extension graph from the extensions folder."""
        return self._read_graph(f"{self.EXTENSION_PATH}/{extension_filename}")

    def save_extension(self, extension_filename: str, g: rdflib.Graph) -> bool:
        """Save the extension graph to the extensions folder."""
        try:
            self._write_graph(f"{self.EXTENSION_PATH}/{extension_filename}", g)
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Error saving extension: {e}")
            return False

    def save_core_ontology(self, g: rdflib.Graph) -> bool:
        """Save modifications directly to the vendored core ontology file.

        Only permitted on local (file) workspaces; remote workspaces treat the
        shared core as read-only.
        """
        if self.core_readonly:
            print("❌ Core ontology is read-only on this workspace. Create an extension instead.")
            return False
        try:
            g.bind("dici_onto", dici_onto)
            g.serialize(destination=self.CORE_ONTOLOGY_FILE, format="ttl")
            return True
        except Exception as e:
            print(f"Error saving core ontology: {e}")
            return False

    def merge_ontologies(self, extension_filename: str) -> rdflib.Graph:
        """Merge core ontology with the extension graph."""
        core = self.load_core_ontology()
        ext = self.load_extension(extension_filename)
        merged = core + ext
        merged.bind("dici_onto", dici_onto)
        return merged

    def update_temp_and_export(self, extension_filename: str) -> Dict[str, str]:
        """Update both the temp working file and export file based on the merged ontology."""
        try:
            merged = self.merge_ontologies(extension_filename)
            base_name = extension_filename.replace(".ttl", "")
            temp_filename = base_name + "_temp.ttl"
            export_filename = base_name + "_export.ttl"
            ttl_content = merged.serialize(format="ttl")

            self._write_text(f"{self.TEMP_PATH}/{temp_filename}", ttl_content)
            self._write_text(f"{self.EXPORTS_PATH}/{export_filename}", ttl_content)
            return {"temp": temp_filename, "export": export_filename}
        except Exception as e:
            print(f"Error updating temp and export: {e}")
            return {}

    def update_temp_and_export_core_mod(self) -> Dict[str, str]:
        """Update temp/export files for core ontology modifications (view/edit)."""
        try:
            core = self.load_core_ontology()
            core.bind("dici_onto", dici_onto)
            temp_filename = "dici_onto_core_mod_temp.ttl"
            export_filename = "dici_onto_core_mod_export.ttl"
            ttl_content = core.serialize(format="ttl")

            self._write_text(f"{self.TEMP_PATH}/{temp_filename}", ttl_content)
            self._write_text(f"{self.EXPORTS_PATH}/{export_filename}", ttl_content)
            return {"temp": temp_filename, "export": export_filename}
        except Exception as e:
            print(f"Error updating core mod temp and export: {e}")
            return {}

    def load_extension_and_update(self, extension_filename: str) -> Tuple[bool, str]:
        """Load extension and update temp/export files."""
        try:
            if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
                # Loading core works on every backend (it merges the vendored core
                # into a workspace temp file for viewing). Saving stays gated by
                # save_core_ontology (local-only).
                self.update_temp_and_export_core_mod()
                return True, "Core ontology loaded"

            extensions = self.list_extension_files()
            ttl_extensions = [e for e in extensions if e.endswith(".ttl")]
            if extension_filename not in ttl_extensions:
                return False, f"Extension file '{extension_filename}' not found"

            self.update_temp_and_export(extension_filename)
            return True, f"Extension {extension_filename} loaded successfully"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"Error loading extension: {str(e)}"

    def _load_temp_graph(self, extension_filename: str) -> Optional[rdflib.Graph]:
        """Load the temp graph for an extension (or core mod)."""
        if extension_filename == "CORE_ONTOLOGY_MODIFICATION":
            temp_filename = "dici_onto_core_mod_temp.ttl"
        else:
            temp_filename = extension_filename.replace(".ttl", "_temp.ttl")

        content = self._read_text(f"{self.TEMP_PATH}/{temp_filename}")
        if content is None:
            return None
        try:
            g = rdflib.Graph()
            g.parse(data=content, format="ttl")
            return g
        except Exception as e:
            print(f"Error loading temp file: {e}")
            return None

    # =================== Utility Functions ===================

    def get_qudt_units(self) -> List[str]:
        """Get available QUDT units from the vendored imports file."""
        units_file = getattr(self, "IMPORTS_PATH", None)
        units_file = os.path.join(units_file, "qudt_units.txt") if units_file else None
        if not units_file or not os.path.exists(units_file):
            units_file = os.path.join(self._resolve_global_ontology_dir(), "imports", "qudt_units.txt")
        try:
            with open(units_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading vendored QUDT units ({units_file}): {e}")
            return []
        units = [line.strip() for line in content.split("\n") if line.strip()]
        return sorted(units, key=str.lower)

    def get_temporal_precisions(self) -> List[Dict[str, str]]:
        """Get available temporal precision options for Event attributes."""
        return [
            {"value": "Year", "label": "Year only (e.g., 2023)"},
            {"value": "YearMonth", "label": "Year-Month (e.g., 2023-06)"},
            {"value": "Date", "label": "Full date (e.g., 2023-06-15)"},
            {"value": "DateTime", "label": "Date and time (e.g., 2023-06-15T14:30:00)"}
        ]

    # =================== Active Extension Tracking ===================

    def _active_extension_path(self) -> str:
        """Workspace-relative path for the active extension marker file."""
        return f"{self.WORKSPACE_ONTOLOGY_ROOT}/active_extension.json"

    def get_active_extension(self) -> Optional[Dict[str, str]]:
        """Return active extension metadata, or None if not set.

        Returns dict with keys: 'extension', 'uploaded_at'.
        """
        content = self._read_text(self._active_extension_path())
        if content:
            try:
                return json.loads(content)
            except Exception:
                pass
        return None

    def set_active_extension(self, extension_filename: str) -> None:
        """Write the active extension marker after a successful GraphDB upload."""
        from datetime import datetime
        metadata = {
            "extension": extension_filename,
            "uploaded_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        }
        try:
            self._write_text(self._active_extension_path(), json.dumps(metadata))
        except Exception as e:
            print(f"⚠️ Could not save active extension marker: {e}")

    def get_workspace_info(self) -> Dict[str, Any]:
        """Get information about the current workspace configuration."""
        return {
            "workspace_id": self.workspace_id,
            "storage_protocol": self.storage.protocol,
            "storage_root": self.storage.root,
            "core_readonly": self.core_readonly,
            "graphdb_available": self.graphdb_client is not None,
            "core_ontology_source": self.CORE_ONTOLOGY_FILE,
        }
