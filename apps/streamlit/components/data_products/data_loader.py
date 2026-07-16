# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Data Loader Module - REBUILT FROM SCRATCH
File: components/data_products/data_loader.py

Uses environment variables for authentication like the working script.
Each data product is a folder containing:
- FOLDER_NAME/FOLDER_NAME.ttl
- FOLDER_NAME/resources/[various resource files]
"""

import streamlit as st
from typing import Dict, List, Optional
from pathlib import Path
import base64
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
import io
import json
import pandas as pd
import os  # Import os for environment variables

# Import TTL parser
from backend.data_products.ttl_parser import TTLParser


@dataclass
class Resource:
    """Represents a single resource file within a data product."""
    name: str
    path: str
    type: str
    size: int = 0
    last_modified: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'path': self.path,
            'type': self.type,
            'size': self.size,
            'last_modified': self.last_modified
        }


class DataProductProcessor:
    """
    Processes data product folders to extract structure and metadata.
    This is the working implementation from the NextCloud script.
    """

    def __init__(self, workspace_id: Optional[str] = None):
        """Initialize with optional workspace for private data products.

        Workspace-aware: if the active session has a WorkspaceContext (via the
        registry), reads data products from the workspace's own
        private_data_products/ via WorkspaceStorage. Falls back to legacy
        NextCloud paths when no workspace storage is available.
        """
        import os

        self.workspace_id = workspace_id
        self.workspace_client = None
        self.global_client = None
        self.parser = TTLParser()

        # Get credentials from environment variables (same as working script)
        self.username = os.getenv("NEXTCLOUD_BASIC_USERNAME", "")
        self.password = os.getenv("NEXTCLOUD_BASIC_PASSWORD", "")
        self.base_url = os.getenv("NEXTCLOUD_BASE_URL", "")

        # Try to get workspace from session or parameter
        if not self.workspace_id:
            current_workspace = st.session_state.get('current_workspace')
            if current_workspace:
                self.workspace_id = current_workspace.get('id')
                self.workspace_name = current_workspace.get('name', '')

        # Pick up the WorkspaceContext if the registry knows this workspace.
        self.workspace_storage = None
        try:
            ctx = st.session_state.get("workspace_context")
            if ctx is None and self.workspace_id:
                from backend.workspace import load_registry
                ctx = load_registry().by_id(self.workspace_id)
            if ctx is not None:
                self.workspace_storage = ctx.storage
        except Exception as e:
            print(f"[data_products] workspace storage lookup skipped: {e}")

        # "Open" (global) data products: a local library dir that works without
        # NextCloud, mirroring the data/global_services convention used by the
        # service catalog. Present → global products are read via WorkspaceStorage
        # (same code path as private); absent → fall back to the NextCloud global
        # store below. The two are unioned so both sources show up when available.
        self.global_storage = None
        try:
            global_dir = os.environ.get("GLOBAL_DATA_PRODUCTS_DIR", "data/global_open_data_products")
            if Path(global_dir).is_dir():
                from backend.workspace.storage import WorkspaceStorage
                self.global_storage = WorkspaceStorage.local(global_dir)
        except Exception as e:
            print(f"[data_products] global data-products storage lookup skipped: {e}")

        # Setup authentication (still needed for NextCloud-backed workspaces + open_data_products)
        if self.username and self.password:
            self.auth = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            self.headers = {"Authorization": f"Basic {self.auth}"}
        else:
            self.headers = {}
            if self.workspace_storage is None:
                st.warning("NextCloud credentials not found in environment variables (NEXTCLOUD_BASIC_USERNAME, NEXTCLOUD_BASIC_PASSWORD)")

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

    # =====================================================================
    # NEW OPTIMIZED METHODS - Fast metadata-only operations
    # =====================================================================

    def get_product_metadata(self, product_name: str, is_private: bool = True) -> Optional[Dict]:
        """
        FAST: Get lightweight metadata WITHOUT parsing TTL.
        """
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
                print(f"[data_products] storage metadata read failed for {product_name}: {e}")

        try:
            if is_private:
                if not self.workspace_id:
                    return None
                folder_path = f"{self.workspace_id}/private_data_products/{product_name}"
                base_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{self.workspace_id}/private_data_products/{product_name}"
            else:
                folder_path = f"global/open_data_products/{product_name}"
                base_url = f"{self.base_url}/remote.php/dav/files/{self.username}/global/open_data_products/{product_name}"

            root = self._propfind_request(base_url)
            if root is None:
                return None

            namespaces = {'d': 'DAV:'}
            ttl_found = False
            actual_ttl_filename = None
            ttl_size = 0
            ttl_modified = None

            for response_elem in root.findall('.//d:response', namespaces):
                href = response_elem.find('d:href', namespaces)
                props = response_elem.find('.//d:prop', namespaces)

                if href is not None:
                    filename = href.text.rstrip('/').split('/')[-1]
                    if filename.endswith('.ttl'):
                        ttl_found = True
                        actual_ttl_filename = filename

                        if props is not None:
                            size_elem = props.find('d:getcontentlength', namespaces)
                            modified_elem = props.find('d:getlastmodified', namespaces)
                            if size_elem is not None:
                                ttl_size = int(size_elem.text)
                            if modified_elem is not None:
                                ttl_modified = modified_elem.text
                        break

            if not ttl_found:
                return None

            if is_private:
                ttl_path = f"{self.workspace_id}/private_data_products/{product_name}/{actual_ttl_filename}"
            else:
                ttl_path = f"global/open_data_products/{product_name}/{actual_ttl_filename}"

            resources_path = f"{folder_path}/resources"
            resource_count = self._count_files_in_folder(resources_path)
            component_estimate = max(1, ttl_size // 1000)

            return {
                'name': product_name,
                'folder_path': folder_path,
                'ttl_path': ttl_path,
                'is_private': is_private,
                'ttl_size': ttl_size,
                'resource_count': resource_count,
                'component_count': component_estimate,
                'last_modified': ttl_modified
            }

        except Exception:
            return None

    def _count_files_in_folder(self, folder_path: str) -> int:
        """Count files in folder WITHOUT downloading"""
        try:
            folder_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{folder_path}"
            headers = {**self.headers, "Depth": "1"}
            propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
            <d:propfind xmlns:d="DAV:">
                <d:prop><d:resourcetype/></d:prop>
            </d:propfind>"""

            response = requests.request("PROPFIND", folder_url, headers=headers,
                                       data=propfind_body, timeout=30)

            if response.status_code not in [200, 207]:
                return 0

            root = ET.fromstring(response.content)
            namespaces = {'d': 'DAV:'}

            count = 0
            for response_elem in root.findall('.//d:response', namespaces):
                href = response_elem.find('d:href', namespaces)
                props = response_elem.find('.//d:prop', namespaces)

                if href and props:
                    resourcetype = props.find('.//d:resourcetype', namespaces)
                    is_folder = resourcetype is not None and \
                               resourcetype.find('d:collection', namespaces) is not None

                    if href.text.rstrip('/').endswith(folder_path.split('/')[-1]):
                        continue

                    if not is_folder:
                        count += 1

            return count

        except Exception:
            return 0

    def list_private_folders(self) -> List[str]:
        """
        List folders in workspace/private_data_products location.
        Direct implementation from the working script.
        """
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
                print(f"[data_products] workspace storage listing failed, falling back to NextCloud: {e}")

        try:
            # Build folder URL for private_data_products
            folder_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{self.workspace_id}/private_data_products"

            headers = {
                **self.headers,
                "Depth": "1"
            }

            # Use PROPFIND to list contents
            propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
            <d:propfind xmlns:d="DAV:">
                <d:prop>
                    <d:displayname/>
                    <d:resourcetype/>
                </d:prop>
            </d:propfind>"""

            response = requests.request(
                "PROPFIND",
                folder_url,
                headers=headers,
                data=propfind_body,
                timeout=60
            )

            if response.status_code not in [200, 207]:
                return []

            # Parse XML response
            root = ET.fromstring(response.content)
            namespaces = {'d': 'DAV:'}

            folders = []

            # Process each response element
            for response_elem in root.findall('.//d:response', namespaces):
                href = response_elem.find('d:href', namespaces)
                props = response_elem.find('.//d:prop', namespaces)

                if href is not None and props is not None:
                    href_text = href.text
                    resourcetype = props.find('.//d:resourcetype', namespaces)

                    # Check if it's a collection (folder)
                    is_collection = resourcetype is not None and \
                                   resourcetype.find('d:collection', namespaces) is not None

                    # Extract the name from href
                    name = href_text.rstrip('/').split('/')[-1]

                    # Skip the parent directory itself
                    if href_text.rstrip('/').endswith('private_data_products'):
                        continue

                    if is_collection:
                        folders.append(name)

            return folders

        except Exception as e:
            st.warning(f"Failed to list private folders: {e}")
            return []

    def list_open_folders(self) -> List[str]:
        """
        List folders in global/open_data_products location.
        Direct implementation from the working script.
        """
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
                print(f"[data_products] local global listing failed: {e}")

        # "Open" (global) data products also live in a shared NextCloud location.
        # In local mode base_url/username are empty (invalid URL) — skip and return
        # whatever the local library gave us instead of erroring.
        if not self.base_url or not self.username:
            return sorted(set(folders))
        try:
            # Build folder URL for open_data_products
            folder_url = f"{self.base_url}/remote.php/dav/files/{self.username}/global/open_data_products"

            headers = {
                **self.headers,
                "Depth": "1"
            }

            # Use PROPFIND to list contents
            propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
            <d:propfind xmlns:d="DAV:">
                <d:prop>
                    <d:displayname/>
                    <d:resourcetype/>
                </d:prop>
            </d:propfind>"""

            response = requests.request(
                "PROPFIND",
                folder_url,
                headers=headers,
                data=propfind_body,
                timeout=60
            )

            if response.status_code not in [200, 207]:
                return sorted(set(folders))

            # Parse XML response
            root = ET.fromstring(response.content)
            namespaces = {'d': 'DAV:'}

            # Process each response element (append to any local results above)
            for response_elem in root.findall('.//d:response', namespaces):
                href = response_elem.find('d:href', namespaces)
                props = response_elem.find('.//d:prop', namespaces)

                if href is not None and props is not None:
                    href_text = href.text
                    resourcetype = props.find('.//d:resourcetype', namespaces)

                    # Check if it's a collection (folder)
                    is_collection = resourcetype is not None and \
                                   resourcetype.find('d:collection', namespaces) is not None

                    # Extract the name from href
                    name = href_text.rstrip('/').split('/')[-1]

                    # Skip the parent directory itself
                    if href_text.rstrip('/').endswith('open_data_products'):
                        continue

                    if is_collection:
                        folders.append(name)

            return sorted(set(folders))

        except Exception as e:
            st.warning(f"Failed to list open folders: {e}")
            return sorted(set(folders))

    def process_data_product(self, product_name: str, is_private: bool = True) -> Optional[Dict]:
        """
        Process a single data product folder to extract its structure.
        Fixed to follow the working logic from data_product_client.py
        """
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
                print(f"[data_products] storage process_data_product failed for {product_name}: {e}")

        try:
            # Build paths based on the working client logic
            if is_private:
                if not self.workspace_id:
                    st.warning("Workspace ID required for private data products")
                    return None

                # Private data product paths - following client structure
                base_path = f"{self.workspace_id}/private_data_products/{product_name}"
                ttl_path = f"{self.workspace_id}/private_data_products/{product_name}/{product_name}.ttl"
                resource_path = f"{self.workspace_id}/private_data_products/{product_name}/resources"

                # Build full URLs for download
                ttl_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{ttl_path}"
                base_url_for_listing = f"{self.base_url}/remote.php/dav/files/{self.username}/{self.workspace_id}/private_data_products/{product_name}"

            else:
                # Open/global data product paths - following client structure
                base_path = f"global/open_data_products/{product_name}"
                ttl_path = f"global/open_data_products/{product_name}/{product_name}.ttl"
                resource_path = f"global/open_data_products/{product_name}/resources"

                # Build full URLs for download
                ttl_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{ttl_path}"
                base_url_for_listing = f"{self.base_url}/remote.php/dav/files/{self.username}/global/open_data_products/{product_name}"

            # First, verify the data product folder exists by listing its contents
            root = self._propfind_request(base_url_for_listing)
            if root is None:
                return None

            # Look for TTL file in the folder listing
            namespaces = {'d': 'DAV:'}
            ttl_found = False
            actual_ttl_filename = None

            for response_elem in root.findall('.//d:response', namespaces):
                href = response_elem.find('d:href', namespaces)
                if href is not None:
                    filename = href.text.rstrip('/').split('/')[-1]
                    if filename.endswith('.ttl'):
                        ttl_found = True
                        actual_ttl_filename = filename
                        break

            if not ttl_found:
                return None

            # Update TTL path if different from expected
            if actual_ttl_filename != f"{product_name}.ttl":
                if is_private:
                    ttl_path = f"{self.workspace_id}/private_data_products/{product_name}/{actual_ttl_filename}"
                else:
                    ttl_path = f"global/open_data_products/{product_name}/{actual_ttl_filename}"
                ttl_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{ttl_path}"

            # Try to download TTL file
            response = requests.get(ttl_url, headers=self.headers, timeout=60)

            if response.status_code != 200:
                return None

            ttl_content = response.text
            if not ttl_content or ttl_content.strip() == "":
                return None

            # Parse TTL content using the existing parser
            try:
                graph = self.parser.parse_ttl_content(ttl_content)
                if not graph:
                    # Continue anyway - we can still show the data product
                    components = {}
                else:
                    components = self.parser.extract_components_from_graph(graph)
            except Exception as e:
                components = {}
                graph = None

            # List resources in the resources folder
            resources = self._list_resources(resource_path, is_private)

            # Link resources to components based on resource references in attributes
            self._link_resources_to_components(components, resources)

            # Return data product dictionary following the expected structure
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
                'ttl_filename': actual_ttl_filename
            }

        except Exception as e:
            st.error(f"Error processing {product_name}: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return None

    def _propfind_request(self, url: str) -> Optional[ET.Element]:
        """
        Make a PROPFIND request to get folder/file information.
        Added this method from the working client.
        """
        propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
        <d:propfind xmlns:d="DAV:">
            <d:prop>
                <d:displayname/>
                <d:resourcetype/>
                <d:getcontentlength/>
                <d:getlastmodified/>
                <d:getcontenttype/>
            </d:prop>
        </d:propfind>"""

        try:
            response = requests.request(
                "PROPFIND",
                url,
                headers=self.headers,
                data=propfind_body,
                timeout=60
            )

            if response.status_code not in [200, 207]:
                return None

            return ET.fromstring(response.content)
        except Exception as e:
            return None

    def _list_resources(self, resource_path: str, is_private: bool) -> List[Dict]:
        """List all files in the resources folder."""
        resources = []

        try:
            # Build the correct folder URL
            # resource_path already contains the full path including workspace for private
            folder_url = f"{self.base_url}/remote.php/dav/files/{self.username}/{resource_path}"

            headers = {
                **self.headers,
                "Depth": "1"
            }

            propfind_body = """<?xml version="1.0" encoding="UTF-8"?>
            <d:propfind xmlns:d="DAV:">
                <d:prop>
                    <d:displayname/>
                    <d:resourcetype/>
                    <d:getcontentlength/>
                    <d:getlastmodified/>
                </d:prop>
            </d:propfind>"""

            response = requests.request(
                "PROPFIND",
                folder_url,
                headers=headers,
                data=propfind_body,
                timeout=60
            )

            if response.status_code in [200, 207]:
                root = ET.fromstring(response.content)
                namespaces = {'d': 'DAV:'}

                for response_elem in root.findall('.//d:response', namespaces):
                    href = response_elem.find('d:href', namespaces)
                    props = response_elem.find('.//d:prop', namespaces)

                    if href is not None and props is not None:
                        resourcetype = props.find('.//d:resourcetype', namespaces)

                        # Check if it's a file (not a collection)
                        is_file = resourcetype is None or \
                                 resourcetype.find('d:collection', namespaces) is None

                        if is_file:
                            filename = href.text.rstrip('/').split('/')[-1]

                            # Skip the parent directory itself (resources folder)
                            if filename and filename != 'resources':
                                size_elem = props.find('d:getcontentlength', namespaces)
                                modified_elem = props.find('d:getlastmodified', namespaces)

                                file_ext = Path(filename).suffix.lower().lstrip('.')

                                resources.append({
                                    'name': filename,
                                    'path': f"{resource_path}/{filename}",
                                    'type': file_ext,
                                    'size': int(size_elem.text) if size_elem is not None and size_elem.text else 0,
                                    'last_modified': modified_elem.text if modified_elem is not None else None
                                })
            else:
                # If resources folder doesn't exist, that's ok - just return empty list
                pass

        except Exception as e:
            # Don't show errors for missing resources folders - they're optional
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

        # Process private data products
        if self.workspace_id:
            private_folders = self.list_private_folders()

            if private_folders:
                for folder_name in private_folders:
                    with st.spinner(f"Processing private: {folder_name}"):
                        product = self.process_data_product(folder_name, is_private=True)
                        if product:
                            all_products[f"private:{folder_name}"] = product
                        # Removed individual success/warning messages

            # Process open data products
            open_folders = self.list_open_folders()

            if open_folders:
                for folder_name in open_folders:
                    with st.spinner(f"Processing open: {folder_name}"):
                        product = self.process_data_product(folder_name, is_private=False)
                        if product:
                            all_products[f"global:{folder_name}"] = product
                        # Removed individual success/warning messages

        # Single summary message at the end
        if all_products:
            st.success(f"✅ Loaded {len(all_products)} data products")
        else:
            st.warning("No data products found")

        return all_products

    def load_resource_file(self, product: Dict, resource_filename: str):
        """Load a resource file from a data product's resources folder."""
        # Backend-agnostic path: read directly via WorkspaceStorage. Private
        # products come from the workspace, global ones from the local library.
        is_private = product.get('type') == 'private'
        storage = self._storage_for(is_private)
        if storage is not None:
            try:
                folder_rel = self._folder_rel(product['name'], is_private)
                rel = f"{folder_rel}/resources/{resource_filename}"
                if not storage.exists(rel):
                    st.error(f"Resource {resource_filename} not found in storage")
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
                print(f"[data_products] storage resource read failed for {resource_filename}: {e}")

        try:
            # Build full path to resource - ensure we use the lowercase resources path
            resource_path = product.get('resource_path', '')
            if not resource_path:
                # Fallback construction if resource_path is missing
                if product['type'] == 'private':
                    resource_path = f"{product.get('workspace_id', '')}/private_data_products/{product['name']}/resources"
                else:
                    resource_path = f"global/open_data_products/{product['name']}/resources"

            full_path = f"{resource_path}/{resource_filename}"

            # Download based on product type
            if product['type'] == 'global':
                # Direct download for global
                url = f"{self.base_url}/remote.php/dav/files/{self.username}/{full_path}"
            else:  # private
                # For private, the workspace_id is already included in the resource_path
                url = f"{self.base_url}/remote.php/dav/files/{self.username}/{full_path}"

            response = requests.get(url, headers=self.headers, timeout=60)

            if response.status_code != 200:
                st.error(f"Failed to load resource {resource_filename}: HTTP {response.status_code}")
                return None

            content = response.text if response.status_code == 200 else None

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
            st.error(f"Error loading resource {resource_filename}: {e}")
            return None


# Wrapper for backwards compatibility
class DataProductLoader:
    """Legacy wrapper that uses DataProductProcessor internally."""

    def __init__(self, workspace_id: Optional[str] = None):
        self.processor = DataProductProcessor(workspace_id)
        self.workspace_id = workspace_id

    def load_all_data_products(self) -> Dict[str, Dict]:
        return self.processor.process_all_data_products()

    def load_resource_file(self, product: Dict, resource_filename: str):
        return self.processor.load_resource_file(product, resource_filename)

    def list_resource_files(self, product: Dict) -> List[str]:
        resources = product.get('resources', [])
        if resources and isinstance(resources[0], dict):
            return [r['name'] for r in resources]
        return resources


def render_data_products_tab(workspace_id: Optional[str] = None):
    """Render the data products loading tab."""
    import os

    st.subheader("📦 Available Data Products")

    # Local mode reads data products from the active workspace's storage
    # (private_data_products/); NextCloud is only needed for the legacy global
    # "open" products. Allow the tab through whenever either is available.
    username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
    password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
    ctx = st.session_state.get("workspace_context")
    has_storage = ctx is not None and getattr(ctx, "storage", None) is not None

    if not has_storage and not (username and password):
        st.info(
            "Open a workspace to browse its `private_data_products/`, "
            "or configure NextCloud credentials for global data products."
        )
        return

    # Initialize processor (wires ctx.storage automatically when a workspace is open)
    processor = DataProductProcessor(workspace_id)

    # Debug info
    with st.expander("🔧 Debug Info", expanded=False):
        st.write(f"Username: {processor.username}")
        st.write(f"Workspace ID: {processor.workspace_id}")
        st.write(f"Base URL: {processor.base_url}")
        st.write(f"Auth configured: {'Yes' if processor.headers.get('Authorization') else 'No'}")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.write("Load and manage TTL data products from NextCloud")

    with col2:
        if st.button("🔄 Load/Refresh", type="primary", use_container_width=True):
            with st.spinner("Loading data products..."):
                products = processor.process_all_data_products()
                st.session_state.loaded_data_products = products

                if products:
                    st.success(f"✅ Loaded {len(products)} data products")
                else:
                    st.warning("No data products found")

    with col3:
        if st.button("🗑️ Clear All", use_container_width=True):
            st.session_state.loaded_data_products = {}
            st.session_state.selected_data_product = None
            st.session_state.selected_component = None
            st.info("Cleared all loaded data products")

    # Display loaded data products
    if 'loaded_data_products' in st.session_state and st.session_state.loaded_data_products:
        st.markdown("---")

        # Summary metrics
        global_count = sum(1 for k in st.session_state.loaded_data_products.keys() if k.startswith("global:"))
        private_count = sum(1 for k in st.session_state.loaded_data_products.keys() if k.startswith("private:"))

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Products", len(st.session_state.loaded_data_products))
        with col2:
            st.metric("🌍 Open", global_count)
        with col3:
            st.metric("🔒 Private", private_count)

        # Product cards
        st.markdown("### Loaded Data Products")

        # Show private products first if any
        if private_count > 0:
            st.markdown("#### 🔒 Private Data Products")
            for key, product in st.session_state.loaded_data_products.items():
                if key.startswith("private:"):
                    with st.expander(f"📁 {product['name']}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"**Folder:** `{product.get('folder_path', product['path'])}/`")
                            st.write(f"**TTL File:** `{product.get('ttl_path', product['path'])}`")
                            st.write(f"**Components:** {product.get('component_count', 0)}")
                            st.write(f"**Component Types:** {', '.join(product.get('component_types', []))}")

                            # Show available resources
                            resources = product.get('resources', [])
                            if resources:
                                st.write(f"**Resources ({len(resources)} files):**")
                                for i, resource in enumerate(resources[:5]):
                                    if isinstance(resource, dict):
                                        st.caption(f"  • {resource['name']} ({resource['type']})")
                                    else:
                                        st.caption(f"  • {resource}")
                                if len(resources) > 5:
                                    st.caption(f"  ... and {len(resources) - 5} more")

                        with col2:
                            if st.button(f"Select", key=f"select_{key}", use_container_width=True):
                                st.session_state.selected_data_product = key
                                st.success(f"Selected: {product['name']}")
                                st.rerun()

                            if st.session_state.get('selected_data_product') == key:
                                st.success("✅ Selected")

        # Show global/open products
        if global_count > 0:
            st.markdown("#### 🌍 Open Data Products")
            for key, product in st.session_state.loaded_data_products.items():
                if key.startswith("global:"):
                    with st.expander(f"📁 {product['name']}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"**Folder:** `{product.get('folder_path', product['path'])}/`")
                            st.write(f"**TTL File:** `{product.get('ttl_path', product['path'])}`")
                            st.write(f"**Components:** {product.get('component_count', 0)}")
                            st.write(f"**Component Types:** {', '.join(product.get('component_types', []))}")

                            # Show available resources
                            resources = product.get('resources', [])
                            if resources:
                                st.write(f"**Resources ({len(resources)} files):**")
                                for i, resource in enumerate(resources[:5]):
                                    if isinstance(resource, dict):
                                        st.caption(f"  • {resource['name']} ({resource['type']})")
                                    else:
                                        st.caption(f"  • {resource}")
                                if len(resources) > 5:
                                    st.caption(f"  ... and {len(resources) - 5} more")

                        with col2:
                            if st.button(f"Select", key=f"select_{key}", use_container_width=True):
                                st.session_state.selected_data_product = key
                                st.success(f"Selected: {product['name']}")
                                st.rerun()

                            if st.session_state.get('selected_data_product') == key:
                                st.success("✅ Selected")
    else:
        st.info("👆 Click 'Load/Refresh' to load available data products")

        # Help section
        with st.expander("ℹ️ About Data Products"):
            st.markdown("""
            **Data Products** are self-contained folders with TTL-based semantic descriptions and associated resources.
            
            **Structure:**
            ```
            DATA_PRODUCT_NAME/
            ├── DATA_PRODUCT_NAME.ttl    # Component definitions
            └── resources/                # Associated data files (lowercase)
                ├── timeseries.csv
                ├── geo.geojson
                └── weather.epw
            ```
            
            **Locations:**
            - **🌍 Open**: `{username}/global/open_data_products/FOLDER_NAME/`
            - **🔒 Private**: `{username}/{workspace}/private_data_products/FOLDER_NAME/`
            
            The system lists all folders in these locations and processes each as a data product.
            """)