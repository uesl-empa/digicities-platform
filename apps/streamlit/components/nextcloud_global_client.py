# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/nextcloud_global_client.py
"""
Additional NextCloud client specifically for global directory access.
This extends your existing NextcloudClient to work with the global/ folder
without modifying the original functionality.
Enhanced with specific support for services folder access.
"""

import os
import json
from typing import Dict, List, Any, Optional
from components.nextcloud_client import NextcloudClient


class NextcloudGlobalClient(NextcloudClient):
    """
    Extension of your existing NextcloudClient that specifically handles
    the global/ directory for data products access and services folder.
    """

    def __init__(self,
                 base_url: str = None,
                 username: str = None,
                 password: str = None):
        """
        Initialize using the existing NextcloudClient but set workspace to 'global'
        """
        super().__init__(
            base_url=base_url,
            username=username,
            password=password,
            workspace_id="global"  # Always use 'global' workspace
        )

    def list_services_files(self) -> List[str]:
        """
        Get list of YAML files in the services folder.
        Returns just the filenames in the services directory.
        """
        try:
            return self.list_files_in_subfolder("services")
        except Exception as e:
            print(f"Error listing services files: {e}")
            return []

    def get_service_file_content(self, filename: str) -> str:
        """
        Load a specific service YAML file from the services folder.
        Args:
            filename: The filename (e.g., "WindForecasting.yaml")
        Returns:
            The content of the YAML file as string
        """
        try:
            filepath = f"services/{filename}"
            return self.download_global_file(filepath)
        except Exception as e:
            print(f"Error loading service file '{filename}': {e}")
            return ""

    def list_catalog_files(self) -> List[str]:
        """
        Get list of JSON files in the data_products/catalogs folder.
        Returns just the catalog names (without .json extension)
        """
        try:
            # List files in the catalogs subdirectory
            folder_path = "data_products/catalogs"

            # Use the existing list_files method but we need to handle subdirectories
            # Since your original client doesn't handle subdirectories, we'll modify the URL directly
            original_workspace = self.workspace_id

            # Temporarily change workspace to include the subdirectory
            self.workspace_id = f"global/{folder_path}"

            try:
                files = self.list_files()
                catalog_names = []

                for file_info in files:
                    filename = file_info["name"]
                    if filename.endswith(".json"):
                        # Return filename without extension
                        catalog_names.append(filename[:-5])

                return catalog_names

            finally:
                # Restore original workspace
                self.workspace_id = original_workspace

        except Exception as e:
            print(f"Error listing catalog files: {e}")
            return []

    def get_catalog_data(self, catalog_name: str) -> Dict[str, Any]:
        """
        Load a specific data product catalog.
        """
        try:
            filepath = f"data_products/catalogs/{catalog_name}.json"
            content = self.download_text_file(filepath)
            return json.loads(content)

        except Exception as e:
            print(f"Error loading catalog '{catalog_name}': {e}")
            return {}

    def list_files_in_subfolder(self, subfolder_path: str) -> List[str]:
        """
        List files in a subfolder within the global directory.
        Args:
            subfolder_path: Path like "data_products/time_series/generation" or "services"
        """
        try:
            original_workspace = self.workspace_id

            # Temporarily change workspace to include the subdirectory
            # Remove any trailing slashes to avoid double slashes
            clean_subfolder = subfolder_path.rstrip('/')
            self.workspace_id = f"global/{clean_subfolder}"

            try:
                files = self.list_files()
                return [file_info["name"] for file_info in files]

            finally:
                # Restore original workspace
                self.workspace_id = original_workspace

        except Exception as e:
            print(f"Error listing files in subfolder '{subfolder_path}': {e}")
            return []

    def download_global_file(self, filepath: str) -> str:
        """
        Download a text file from the global directory.
        Args:
            filepath: Path like "data_products/catalogs/tech_catalog.json" or "services/WindForecasting.yaml"
        """
        return self.download_text_file(filepath)

    def upload_global_file(self, filepath: str, content: str) -> bool:
        """
        Upload a file to the global directory.
        Args:
            filepath: Path like "data_products/catalogs/new_catalog.json" or "services/NewService.yaml"
            content: File content as string
        """
        return self.upload_file(filepath, content)

    def verify_services_folder_access(self) -> Dict[str, Any]:
        """
        Specifically verify access to the services folder and return detailed status.
        This helps debug the "No YAML input files found" error.
        """
        status = {
            "services_folder_accessible": False,
            "services_files_found": [],
            "yaml_files_found": [],
            "errors": [],
            "debug_info": {}
        }

        try:
            # First, check if we can access the global root
            try:
                root_files = self.list_files()
                status["debug_info"]["global_root_accessible"] = True
                status["debug_info"]["global_root_files"] = [f.get("name", "Unknown") for f in root_files[:10]]
            except Exception as root_error:
                status["errors"].append(f"Cannot access global root: {root_error}")
                status["debug_info"]["global_root_accessible"] = False

            # Try to access services folder specifically
            try:
                services_files = self.list_files_in_subfolder("services")
                status["services_folder_accessible"] = True
                status["services_files_found"] = services_files

                # Filter for YAML files
                yaml_files = [f for f in services_files if f.endswith(('.yaml', '.yml'))]
                status["yaml_files_found"] = yaml_files

                status["debug_info"]["services_folder_method"] = "list_files_in_subfolder"

            except Exception as services_error:
                status["errors"].append(f"Cannot access services folder: {services_error}")

                # Try alternative method - direct workspace change
                try:
                    original_workspace = self.workspace_id
                    self.workspace_id = "global/services"

                    try:
                        alt_files = self.list_files()
                        alt_services_files = [f.get("name", "Unknown") for f in alt_files]

                        status["services_folder_accessible"] = True
                        status["services_files_found"] = alt_services_files
                        status["yaml_files_found"] = [f for f in alt_services_files if f.endswith(('.yaml', '.yml'))]
                        status["debug_info"]["services_folder_method"] = "direct_workspace_change"

                    finally:
                        self.workspace_id = original_workspace

                except Exception as alt_error:
                    status["errors"].append(f"Alternative services access failed: {alt_error}")

            # Test downloading a YAML file if any found
            if status["yaml_files_found"]:
                try:
                    test_file = status["yaml_files_found"][0]
                    test_content = self.get_service_file_content(test_file)
                    if test_content:
                        status["debug_info"]["can_download_yaml"] = True
                        status["debug_info"]["test_file_size"] = len(test_content)
                    else:
                        status["debug_info"]["can_download_yaml"] = False
                        status["errors"].append("YAML file download returned empty content")
                except Exception as download_error:
                    status["errors"].append(f"Cannot download YAML file: {download_error}")
                    status["debug_info"]["can_download_yaml"] = False

        except Exception as general_error:
            status["errors"].append(f"General error in services verification: {general_error}")

        return status

    def debug_global_structure(self) -> Dict[str, Any]:
        """
        Debug the global directory structure with enhanced services folder checking.
        """
        structure = {}

        try:
            # Check root of global
            root_files = self.list_files()
            structure["global_root"] = [f["name"] for f in root_files]

            # Check for services folder specifically
            services_verification = self.verify_services_folder_access()
            structure["services_verification"] = services_verification

            # Check data_products folder
            data_products_files = self.list_files_in_subfolder("data_products")
            structure["data_products"] = data_products_files

            # Check catalogs specifically
            catalog_files = self.list_files_in_subfolder("data_products/catalogs")
            structure["catalogs"] = catalog_files

            # Check time series folders
            structure["time_series_generation"] = self.list_files_in_subfolder("data_products/time_series/generation")
            structure["time_series_demand"] = self.list_files_in_subfolder("data_products/time_series/demand")

        except Exception as e:
            structure["error"] = str(e)

        return structure


def get_global_nextcloud_client() -> Optional[NextcloudGlobalClient]:
    """
    Create a NextCloud client for global directory access using your existing client as base.
    """
    try:
        return NextcloudGlobalClient()
    except ValueError as e:
        print(f"Could not create NextCloud global client: {e}")
        return None


def test_services_access():
    """Test services folder access specifically to help debug the YAML loading issue."""
    print("🧪 Testing NextCloud Services Folder Access")
    print("=" * 50)

    try:
        # Create global client
        print("1. Creating NextCloud global client...")
        global_client = get_global_nextcloud_client()
        if not global_client:
            print("❌ Could not create global client")
            return

        print("✅ Global client created successfully")
        print(f"   Workspace ID: {global_client.workspace_id}")

        # Test services folder access specifically
        print("\n2. Testing services folder access...")
        services_status = global_client.verify_services_folder_access()

        print("**Services Folder Access Results:**")
        print(f"   Accessible: {services_status['services_folder_accessible']}")
        print(f"   Files found: {len(services_status['services_files_found'])}")
        print(f"   YAML files: {len(services_status['yaml_files_found'])}")

        if services_status['services_files_found']:
            print("   Services files:")
            for f in services_status['services_files_found']:
                print(f"     - {f}")

        if services_status['yaml_files_found']:
            print("   YAML files:")
            for f in services_status['yaml_files_found']:
                print(f"     - {f}")

        if services_status['errors']:
            print("   Errors:")
            for error in services_status['errors']:
                print(f"     ❌ {error}")

        print("   Debug info:")
        for key, value in services_status['debug_info'].items():
            print(f"     {key}: {value}")

        # Test the full debug structure
        print("\n3. Testing global directory structure...")
        structure = global_client.debug_global_structure()

        for key, value in structure.items():
            if key == "error":
                print(f"❌ Error: {value}")
            elif key == "services_verification":
                print(f"📁 Services verification: {len(value.get('yaml_files_found', []))} YAML files")
            else:
                print(f"📁 {key}: {value}")

        print("\n✅ Services access test completed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")


def test_global_client():
    """Test the global client functionality without breaking existing client."""
    print("🧪 Testing NextCloud Global Client (preserving existing functionality)")
    print("=" * 70)

    try:
        # Test that we can still create the original client
        print("1. Testing original client functionality...")
        original_client = NextcloudClient(workspace_id="test")
        print("✅ Original NextcloudClient still works")

        # Test the new global client
        print("\n2. Testing new global client...")
        global_client = get_global_nextcloud_client()
        if not global_client:
            print("❌ Could not create global client")
            return

        print("✅ Global client created successfully")
        print(f"   Workspace ID: {global_client.workspace_id}")

        # Test global directory structure
        print("\n3. Testing global directory access...")
        structure = global_client.debug_global_structure()

        print(f"Global root contains: {structure.get('global_root', [])}")
        print(f"Data products folder: {structure.get('data_products', [])}")
        print(f"Catalogs folder: {structure.get('catalogs', [])}")

        # Test catalog listing
        print("\n4. Testing catalog file listing...")
        catalogs = global_client.list_catalog_files()
        print(f"Found {len(catalogs)} catalog files: {catalogs}")

        # Test services folder specifically
        print("\n5. Testing services folder access...")
        services_files = global_client.list_services_files()
        print(f"Found {len(services_files)} files in services folder: {services_files}")

        # Try to load a catalog if any exist
        if catalogs:
            print(f"\n6. Testing catalog loading...")
            first_catalog = catalogs[0]
            catalog_data = global_client.get_catalog_data(first_catalog)
            print(f"Loaded catalog '{first_catalog}' with keys: {list(catalog_data.keys())}")

        # Try to load a service file if any exist
        yaml_services = [f for f in services_files if f.endswith(('.yaml', '.yml'))]
        if yaml_services:
            print(f"\n7. Testing service file loading...")
            first_service = yaml_services[0]
            service_content = global_client.get_service_file_content(first_service)
            print(f"Loaded service '{first_service}' with {len(service_content)} characters")

        print("\n✅ All tests completed successfully!")

    except Exception as e:
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    # Run both tests
    test_global_client()
    print("\n" + "=" * 70)
    test_services_access()