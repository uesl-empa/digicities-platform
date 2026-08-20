# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Headless data-product processor (Phase 5, data-products half).

Moved from ``apps/streamlit/components/data_products/data_loader.py``. A data
product is a folder ``NAME/NAME.ttl`` + ``NAME/resources/*``; private products
live under the workspace's ``private_data_products/``, "open" (global) products
in a shared library (a local dir, and/or the legacy NextCloud
``global/open_data_products`` store).

The Streamlit touches the old class made are now seams, in the Phase 4a style
(see ``backend.scenario_builder.use_case_loader``):

* ``st.warning`` / ``st.error`` / ``st.success`` / ``st.code``  ->
  ``on_status(level, message)`` callback, no-op by default. Levels are
  ``"warning"``, ``"error"``, ``"success"``, ``"info"`` and ``"code"`` (the
  Streamlit shim maps them back onto the exact old calls).
* ``st.session_state['current_workspace']`` / ``['workspace_context']``  ->
  explicit ``workspace_id`` / ``workspace_storage`` constructor arguments.
  When no storage is passed the workspace registry is consulted, exactly as
  the old class did when session state had no context.

Storage backends, in resolution order per scope:

* private  — the workspace's ``WorkspaceStorage`` (local disk or WebDAV);
* open     — a local library dir (``GLOBAL_DATA_PRODUCTS_DIR``, default
  ``data/global_open_data_products``) via ``WorkspaceStorage.local``;
* legacy NextCloud fallback for either scope when storage can't serve it.

The legacy fallback used to be a hand-rolled WebDAV PROPFIND XML client; it
now goes through ``backend.nextcloud.NextcloudClient`` (Phase 3's moved
client), whose ``list_files`` / ``list_folders`` / ``download_*`` helpers are
the same PROPFIND/GET requests. Listing behavior is preserved: files only in
file listings, collections only in folder listings, the queried folder itself
excluded, empty results (never raises) on unreachable paths.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from backend.data_products.ttl_parser import TTLParser


class DataProductProcessor:
    """Processes data product folders to extract structure and metadata."""

    def __init__(
        self,
        workspace_id: Optional[str] = None,
        workspace_storage=None,
        global_storage=None,
        on_status: Optional[Callable[[str, str], None]] = None,
    ):
        """Initialize with an optional workspace for private data products.

        Args:
            workspace_id: Workspace whose ``private_data_products/`` to read.
            workspace_storage: A ``WorkspaceStorage`` for that workspace. When
                omitted, the workspace registry is consulted for ``workspace_id``
                (the Streamlit shim passes the session's context storage instead).
            global_storage: Storage for the open/global product library. When
                omitted, ``GLOBAL_DATA_PRODUCTS_DIR`` (default
                ``data/global_open_data_products``) is wrapped if it exists.
            on_status: ``(level, message)`` display callback; levels are
                ``"warning"`` / ``"error"`` / ``"success"`` / ``"info"`` /
                ``"code"``. Defaults to a no-op.
        """
        self.workspace_id = workspace_id
        self.on_status = on_status
        self.workspace_client = None
        self.global_client = None
        self.parser = TTLParser()

        # Credentials for the legacy NextCloud fallback (same env the old code read).
        self.username = os.getenv("NEXTCLOUD_BASIC_USERNAME", "")
        self.password = os.getenv("NEXTCLOUD_BASIC_PASSWORD", "")
        self.base_url = os.getenv("NEXTCLOUD_BASE_URL", "")

        # Private-scope storage: explicit argument first, registry lookup second.
        self.workspace_storage = workspace_storage
        if self.workspace_storage is None and self.workspace_id:
            try:
                from backend.workspace import load_registry

                ctx = load_registry().by_id(self.workspace_id)
                if ctx is not None:
                    self.workspace_storage = ctx.storage
            except Exception as e:
                self._notify("info", f"[data_products] workspace storage lookup skipped: {e}")

        # "Open" (global) data products: a local library dir that works without
        # NextCloud, mirroring the data/global_services convention used by the
        # service catalog. Present → global products are read via WorkspaceStorage
        # (same code path as private); absent → fall back to the NextCloud global
        # store below. The two are unioned so both sources show up when available.
        self.global_storage = global_storage
        if self.global_storage is None:
            try:
                global_dir = os.environ.get(
                    "GLOBAL_DATA_PRODUCTS_DIR", "data/global_open_data_products")
                if Path(global_dir).is_dir():
                    from backend.workspace.storage import WorkspaceStorage

                    self.global_storage = WorkspaceStorage.local(global_dir)
            except Exception as e:
                self._notify(
                    "info", f"[data_products] global data-products storage lookup skipped: {e}")

        # Legacy NextCloud client (still needed for NextCloud-backed workspaces
        # + the shared open_data_products store). Header dict kept for
        # compatibility with the old attribute surface.
        self._nc_client = None
        if self.username and self.password:
            import base64

            auth = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            self.headers = {"Authorization": f"Basic {auth}"}
        else:
            self.headers = {}
            if self.workspace_storage is None:
                self._notify(
                    "warning",
                    "NextCloud credentials not found in environment variables "
                    "(NEXTCLOUD_BASIC_USERNAME, NEXTCLOUD_BASIC_PASSWORD)",
                )

    # ------------------------------------------------------------------ seams

    def _notify(self, level: str, message: str) -> None:
        """Report a status/error message. Silent unless ``on_status`` is set."""
        if self.on_status is not None:
            self.on_status(level, message)

    def _nextcloud(self):
        """The lazily-built ``backend.nextcloud.NextcloudClient`` for the legacy
        WebDAV fallback, or None when credentials/URL aren't configured."""
        if self._nc_client is None:
            if not (self.base_url and self.username and self.password):
                return None
            try:
                from backend.nextcloud import NextcloudClient

                self._nc_client = NextcloudClient(
                    base_url=self.base_url,
                    username=self.username,
                    password=self.password,
                )
            except Exception:
                return None
        return self._nc_client

    # =====================================================================
    # Storage helpers — pick the right backend-agnostic handle per scope.
    # =====================================================================

    def _storage_for(self, is_private: bool):
        """WorkspaceStorage for the given scope: the active workspace for private
        products, the local global library for open products (None if absent)."""
        return self.workspace_storage if is_private else self.global_storage

    @staticmethod
    def _folder_rel(product_name: str, is_private: bool) -> str:
        """Storage-relative folder for a product. Private products live under the
        workspace's ``private_data_products/``; global ones sit at the root of the
        global library dir."""
        return f"private_data_products/{product_name}" if is_private else product_name

    def _display_prefix(self, is_private: bool) -> str:
        """Cosmetic path prefix for the UI (workspace id for private, none for global)."""
        return f"{self.workspace_id}/" if is_private else ""

    # ---- legacy NextCloud path fragments (relative to the DAV files root) ----

    def _nc_folder(self, product_name: str, is_private: bool) -> str:
        if is_private:
            return f"{self.workspace_id}/private_data_products/{product_name}"
        return f"global/open_data_products/{product_name}"

    def _nc_list_files(self, folder_path: str) -> List[Dict]:
        """PROPFIND file listing (never raises; [] on any failure) — the
        replacement for the old hand-rolled ``_propfind_request`` XML client."""
        client = self._nextcloud()
        if client is None:
            return []
        try:
            return client.list_files(workspace_id=folder_path)
        except Exception:
            return []

    def _nc_list_folders(self, folder_path: str) -> List[str]:
        """PROPFIND folder listing, minus the queried folder itself (the old
        code skipped the parent entry the same way)."""
        client = self._nextcloud()
        if client is None:
            return []
        try:
            folders = client.list_folders(workspace_id=folder_path)
        except Exception:
            return []
        parent = folder_path.rstrip("/").split("/")[-1]
        return [f for f in folders if f != parent]

    # =====================================================================
    # Fast metadata-only operations
    # =====================================================================

    def get_product_metadata(self, product_name: str, is_private: bool = True) -> Optional[Dict]:
        """FAST: Get lightweight metadata WITHOUT parsing TTL."""
        # Backend-agnostic path via WorkspaceStorage — works identically for
        # private (workspace) and global (local library) products, local or
        # NextCloud. Falls through to the legacy WebDAV path only when no storage
        # handle is available for this scope.
        storage = self._storage_for(is_private)
        folder_rel = self._folder_rel(product_name, is_private)
        # Only take the storage path when the product actually exists there; if it
        # doesn't, fall through to the NextCloud/WebDAV path (relevant only when
        # both a local global library and NextCloud are configured).
        if storage is not None and storage.glob(f"{folder_rel}/*.ttl"):
            try:
                ttl_candidates = storage.glob(f"{folder_rel}/*.ttl")
                ttl_rel = ttl_candidates[0]
                actual_ttl_filename = ttl_rel.rsplit("/", 1)[-1]
                ttl_size = len(storage.read_text(ttl_rel).encode("utf-8"))
                resources_rel = f"{folder_rel}/resources"
                resource_count = len(storage.glob(f"{resources_rel}/*")) if storage.exists(resources_rel) else 0
                prefix = self._display_prefix(is_private)
                return {
                    'name': product_name,
                    'folder_path': f"{prefix}{folder_rel}",
                    'ttl_path': f"{prefix}{folder_rel}/{actual_ttl_filename}",
                    'is_private': is_private,
                    'ttl_size': ttl_size,
                    'resource_count': resource_count,
                    'component_count': max(1, ttl_size // 1000),
                    'last_modified': None,
                }
            except Exception as e:
                self._notify("info", f"[data_products] storage metadata read failed for {product_name}: {e}")

        try:
            if is_private and not self.workspace_id:
                return None
            folder_path = self._nc_folder(product_name, is_private)

            files = self._nc_list_files(folder_path)
            if not files:
                return None

            ttl_entry = next((f for f in files if f["name"].endswith(".ttl")), None)
            if ttl_entry is None:
                return None
            actual_ttl_filename = ttl_entry["name"]
            ttl_size = ttl_entry.get("size", 0) or 0
            ttl_modified = ttl_entry.get("last_modified")

            ttl_path = f"{folder_path}/{actual_ttl_filename}"
            resources_path = f"{folder_path}/resources"
            resource_count = len(self._nc_list_files(resources_path))
            component_estimate = max(1, ttl_size // 1000)

            return {
                'name': product_name,
                'folder_path': folder_path,
                'ttl_path': ttl_path,
                'is_private': is_private,
                'ttl_size': ttl_size,
                'resource_count': resource_count,
                'component_count': component_estimate,
                'last_modified': ttl_modified,
            }

        except Exception:
            return None

    def list_private_folders(self) -> List[str]:
        """List folders in workspace/private_data_products location."""
        # Workspace-aware path: list subdirs of private_data_products/ via storage.
        if self.workspace_storage is not None:
            try:
                entries = self.workspace_storage.ls("private_data_products", detail=True)
                folders = []
                for entry in entries:
                    name = (entry.get("name") if isinstance(entry, dict) else str(entry)).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
                    is_dir = isinstance(entry, dict) and entry.get("type") in ("directory", "dir")
                    if not isinstance(entry, dict):
                        # local FS ls returns dicts; this branch is just defensive.
                        if self.workspace_storage.isdir(f"private_data_products/{name}"):
                            folders.append(name)
                    elif is_dir and name:
                        folders.append(name)
                return folders
            except Exception as e:
                self._notify("info", f"[data_products] workspace storage listing failed, falling back to NextCloud: {e}")

        if not self.workspace_id:
            return []
        try:
            return self._nc_list_folders(f"{self.workspace_id}/private_data_products")
        except Exception as e:
            self._notify("warning", f"Failed to list private folders: {e}")
            return []

    def list_open_folders(self) -> List[str]:
        """List folders in the open/global data-product locations."""
        folders: List[str] = []

        # Local global library (works without NextCloud). Each subfolder is a product.
        if self.global_storage is not None:
            try:
                for entry in self.global_storage.ls("", detail=True):
                    name = (entry.get("name") if isinstance(entry, dict) else str(entry))
                    name = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
                    is_dir = isinstance(entry, dict) and entry.get("type") in ("directory", "dir")
                    if not isinstance(entry, dict):
                        is_dir = self.global_storage.isdir(name)
                    if is_dir and name:
                        folders.append(name)
            except Exception as e:
                self._notify("info", f"[data_products] local global listing failed: {e}")

        # "Open" (global) data products also live in a shared NextCloud location.
        # In local mode base_url/username are empty — skip and return whatever
        # the local library gave us instead of erroring.
        if not self.base_url or not self.username:
            return sorted(set(folders))
        try:
            folders.extend(self._nc_list_folders("global/open_data_products"))
            return sorted(set(folders))
        except Exception as e:
            self._notify("warning", f"Failed to list open folders: {e}")
            return sorted(set(folders))

    def process_data_product(self, product_name: str, is_private: bool = True) -> Optional[Dict]:
        """Process a single data product folder to extract its structure."""
        # Backend-agnostic fast path — private via workspace storage, global via
        # the local library dir. Same code for both; identical on local disk and
        # NextCloud.
        storage = self._storage_for(is_private)
        folder_rel = self._folder_rel(product_name, is_private)
        # Take the storage path only when the product exists there; otherwise fall
        # through to WebDAV (matters only when both local global + NextCloud exist).
        if storage is not None and storage.glob(f"{folder_rel}/*.ttl"):
            try:
                ttl_candidates = storage.glob(f"{folder_rel}/*.ttl")
                ttl_rel = ttl_candidates[0]
                actual_ttl_filename = ttl_rel.rsplit("/", 1)[-1]
                ttl_content = storage.read_text(ttl_rel)
                if not ttl_content.strip():
                    return None

                resources = []
                resources_rel = f"{folder_rel}/resources"
                if storage.exists(resources_rel):
                    for r_rel in storage.glob(f"{resources_rel}/*"):
                        name = r_rel.rsplit("/", 1)[-1]
                        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                        resources.append({"name": name, "path": r_rel, "type": ext})

                try:
                    graph = self.parser.parse_ttl_content(ttl_content)
                    components = self.parser.extract_components_from_graph(graph) if graph else {}
                except Exception:
                    graph = None
                    components = {}
                self._link_resources_to_components(components, resources)

                prefix = self._display_prefix(is_private)
                return {
                    "name": product_name,
                    "type": "private" if is_private else "global",
                    "ttl_path": f"{prefix}{folder_rel}/{actual_ttl_filename}",
                    "folder_path": f"{prefix}{folder_rel}",
                    "resource_path": f"{prefix}{folder_rel}/resources",
                    "workspace_id": self.workspace_id if is_private else None,
                    "components": components,
                    "graph": graph,
                    "resources": resources,
                    "component_count": sum(len(comps) for comps in components.values()) if components else 0,
                    "ttl_content": ttl_content,
                }
            except Exception as e:
                self._notify("info", f"[data_products] storage process_data_product failed for {product_name}: {e}")

        try:
            if is_private and not self.workspace_id:
                self._notify("warning", "Workspace ID required for private data products")
                return None

            base_path = self._nc_folder(product_name, is_private)
            resource_path = f"{base_path}/resources"

            # Verify the folder exists and find the TTL file in one listing.
            files = self._nc_list_files(base_path)
            if not files:
                return None
            ttl_entry = next((f for f in files if f["name"].endswith(".ttl")), None)
            if ttl_entry is None:
                return None
            actual_ttl_filename = ttl_entry["name"]
            ttl_path = f"{base_path}/{actual_ttl_filename}"

            client = self._nextcloud()
            if client is None:
                return None
            try:
                # _build_url joins "{workspace_id}/{filename}", so the folder
                # path rides in the workspace_id slot.
                ttl_content = client.download_text_file(
                    actual_ttl_filename, workspace_id=base_path)
            except Exception:
                return None
            if not ttl_content or ttl_content.strip() == "":
                return None

            # Parse TTL content using the existing parser
            try:
                graph = self.parser.parse_ttl_content(ttl_content)
                if not graph:
                    components = {}
                else:
                    components = self.parser.extract_components_from_graph(graph)
            except Exception:
                components = {}
                graph = None

            # List resources in the resources folder
            resources = self._list_resources(resource_path, is_private)

            # Link resources to components based on resource references in attributes
            self._link_resources_to_components(components, resources)

            return {
                'name': product_name,
                'type': 'private' if is_private else 'global',
                'path': ttl_path,
                'folder_path': base_path,
                'ttl_path': ttl_path,
                'resource_path': resource_path,
                'components': components,
                'graph': graph,
                'workspace_id': self.workspace_id if is_private else None,
                'component_count': sum(len(comps) for comps in components.values()) if components else 0,
                'component_types': list(components.keys()) if components else [],
                'resources': resources,
                'ttl_content': ttl_content,
                'ttl_filename': actual_ttl_filename,
            }

        except Exception as e:
            self._notify("error", f"Error processing {product_name}: {str(e)}")
            import traceback

            self._notify("code", traceback.format_exc())
            return None

    def _list_resources(self, resource_path: str, is_private: bool) -> List[Dict]:
        """List all files in the (legacy NextCloud) resources folder."""
        resources = []
        try:
            for entry in self._nc_list_files(resource_path):
                filename = entry["name"]
                if not filename or filename == "resources":
                    continue
                file_ext = Path(filename).suffix.lower().lstrip(".")
                resources.append({
                    'name': filename,
                    'path': f"{resource_path}/{filename}",
                    'type': file_ext,
                    'size': entry.get("size", 0) or 0,
                    'last_modified': entry.get("last_modified"),
                })
        except Exception:
            # Don't report errors for missing resources folders — they're optional.
            pass
        return resources

    def _link_resources_to_components(self, components: Dict, resources: List[Dict]) -> None:
        """Link resource files to components based on resource references in attributes"""
        # Create a lookup dict of available resources by filename
        resource_lookup = {res['name']: res for res in resources}

        # Go through all components and link resources based on attribute references
        for comp_type, comp_list in components.items():
            for component in comp_list:
                component_resources = {}

                # Check each attribute for resource references
                attributes = component.get('attributes', {})
                for attr_name, attr_data in attributes.items():
                    if isinstance(attr_data, dict):
                        resource_ref = attr_data.get('resource_reference')
                        if resource_ref:
                            # Extract just the filename from the resource reference
                            if '/' in resource_ref:
                                filename = resource_ref.split('/')[-1]
                            else:
                                filename = resource_ref

                            # Check if this file exists in our resources
                            if filename in resource_lookup:
                                component_resources[attr_name] = filename

                # Add resources to component
                component['resources'] = component_resources

    def process_all_data_products(self) -> Dict[str, Dict]:
        """Process all data products in both open and private locations."""
        all_products = {}

        if self.workspace_id:
            for folder_name in self.list_private_folders():
                product = self.process_data_product(folder_name, is_private=True)
                if product:
                    all_products[f"private:{folder_name}"] = product

            for folder_name in self.list_open_folders():
                product = self.process_data_product(folder_name, is_private=False)
                if product:
                    all_products[f"global:{folder_name}"] = product

        # Single summary message at the end
        if all_products:
            self._notify("success", f"✅ Loaded {len(all_products)} data products")
        else:
            self._notify("warning", "No data products found")

        return all_products

    def load_resource_file(self, product: Dict, resource_filename: str):
        """Load a resource file from a data product's resources folder.

        Returns a DataFrame for CSV, a dict for JSON/GeoJSON, text for other
        text formats, bytes for binaries — or None on failure.
        """
        # Backend-agnostic path: read directly via WorkspaceStorage. Private
        # products come from the workspace, global ones from the local library.
        is_private = product.get('type') == 'private'
        storage = self._storage_for(is_private)
        if storage is not None:
            try:
                folder_rel = self._folder_rel(product['name'], is_private)
                rel = f"{folder_rel}/resources/{resource_filename}"
                if not storage.exists(rel):
                    self._notify("error", f"Resource {resource_filename} not found in storage")
                    return None
                if resource_filename.lower().endswith(('.csv', '.json', '.geojson', '.txt', '.epw')):
                    content = storage.read_text(rel)
                    if resource_filename.lower().endswith('.csv'):
                        return pd.read_csv(io.StringIO(content))
                    if resource_filename.lower().endswith(('.json', '.geojson')):
                        return json.loads(content)
                    return content
                # Binary fallback (images, parquet, etc.)
                return storage.read_bytes(rel)
            except Exception as e:
                self._notify("info", f"[data_products] storage resource read failed for {resource_filename}: {e}")

        try:
            resource_path = product.get('resource_path', '')
            if not resource_path:
                # Fallback construction if resource_path is missing
                if product['type'] == 'private':
                    resource_path = f"{product.get('workspace_id', '')}/private_data_products/{product['name']}/resources"
                else:
                    resource_path = f"global/open_data_products/{product['name']}/resources"

            client = self._nextcloud()
            if client is None:
                self._notify("error", f"Failed to load resource {resource_filename}: NextCloud not configured")
                return None
            try:
                # _build_url joins "{workspace_id}/{filename}" — folder in the
                # workspace_id slot, exactly like the TTL download above.
                content = client.download_text_file(
                    resource_filename, workspace_id=resource_path)
            except Exception as e:
                self._notify("error", f"Failed to load resource {resource_filename}: {e}")
                return None

            if not content:
                return None

            # Parse based on file type
            if resource_filename.endswith('.csv'):
                return pd.read_csv(io.StringIO(content))
            elif resource_filename.endswith('.json') or resource_filename.endswith('.geojson'):
                return json.loads(content)
            elif resource_filename.endswith('.epw'):
                return content
            else:
                return content

        except Exception as e:
            self._notify("error", f"Error loading resource {resource_filename}: {e}")
            return None


__all__ = ["DataProductProcessor"]
