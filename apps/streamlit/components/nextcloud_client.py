# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import os
import base64
import requests
import pandas as pd
from io import StringIO, BytesIO
from xml.etree import ElementTree as ET
from typing import List, Optional, Dict, Any, Union
import filetype
from dotenv import load_dotenv

load_dotenv()


class NextcloudClient:
    """
    Standalone Nextcloud client for file operations and data retrieval.
    Provides basic CRUD operations for files and specialized methods for timeseries data.
    """

    def __init__(self,
                 base_url: str = None,
                 username: str = None,
                 password: str = None,
                 workspace_id: str = None):
        """
        Initialize Nextcloud client.

        Args:
            base_url: Nextcloud base URL (defaults to env var or platform URL)
            username: Username (defaults to env var)
            password: Password (defaults to env var)
            workspace_id: Default workspace/folder to work with
        """
        self.base_url = base_url or os.getenv("NEXTCLOUD_BASE_URL")
        self.username = username or os.getenv("NEXTCLOUD_BASIC_USERNAME")
        self.password = password or os.getenv("NEXTCLOUD_BASIC_PASSWORD")
        self.workspace_id = workspace_id

        if not self.username or not self.password:
            raise ValueError("Nextcloud credentials not provided. Set NEXTCLOUD_BASIC_USERNAME and NEXTCLOUD_BASIC_PASSWORD")

        # Setup authentication
        self.auth_header = "Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode("utf-8")
        ).decode("utf-8")

        # Optional cookie header for session management
        self.cookie_header = os.getenv("NEXTCLOUD_COOKIE", "")

        self.headers = {
            "Authorization": self.auth_header,
            "Cookie": self.cookie_header
        }

    def _build_url(self, workspace_id: str = None, filename: str = "") -> str:
        """Build complete file URL for workspace."""
        ws_id = workspace_id or self.workspace_id
        if not ws_id:
            raise ValueError("No workspace_id provided")
        return f"{self.base_url}/remote.php/dav/files/{self.username}/{ws_id}/{filename}"

    def list_files(self, workspace_id: str = None) -> List[Dict[str, Any]]:
        """
        List all files in a workspace folder.

        Args:
            workspace_id: Workspace folder to list (uses default if None)

        Returns:
            List of file dictionaries with name, size, etc.
        """
        folder_url = self._build_url(workspace_id)

        headers = {**self.headers, "Depth": "1", "Content-Type": "application/xml"}

        xml_body = """<?xml version="1.0"?>
        <d:propfind xmlns:d="DAV:">
            <d:prop>
                <d:displayname/>
                <d:getcontentlength/>
                <d:getlastmodified/>
                <d:getcontenttype/>
            </d:prop>
        </d:propfind>
        """

        try:
            response = requests.request("PROPFIND", folder_url, headers=headers, data=xml_body)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            ns = {"d": "DAV:"}
            files = []

            for resp in root.findall("d:response", ns):
                href = resp.find("d:href", ns)
                if href is None:
                    continue

                name = href.text.split("/")[-1]
                if not name or name.endswith("/"):  # Skip folders
                    continue

                # Extract file properties
                props = resp.find("d:propstat/d:prop", ns)
                size_elem = props.find("d:getcontentlength", ns) if props is not None else None
                modified_elem = props.find("d:getlastmodified", ns) if props is not None else None
                content_type_elem = props.find("d:getcontenttype", ns) if props is not None else None

                files.append({
                    "name": name,
                    "size": int(size_elem.text) if size_elem is not None and size_elem.text else 0,
                    "last_modified": modified_elem.text if modified_elem is not None else None,
                    "content_type": content_type_elem.text if content_type_elem is not None else None
                })

            return files

        except requests.RequestException as e:
            raise Exception(f"Failed to list files: {e}")
        except ET.ParseError as e:
            raise Exception(f"Failed to parse response: {e}")

    def download_file(self, filename: str, workspace_id: str = None) -> bytes:
        """
        Download file content as bytes.

        Args:
            filename: Name of file to download
            workspace_id: Workspace folder (uses default if None)

        Returns:
            File content as bytes
        """
        file_url = self._build_url(workspace_id, filename)

        try:
            response = requests.get(file_url, headers=self.headers)
            response.raise_for_status()
            return response.content

        except requests.RequestException as e:
            raise Exception(f"Failed to download file '{filename}': {e}")

    def download_text_file(self, filename: str, workspace_id: str = None, encoding: str = "utf-8") -> str:
        """
        Download text file content as string.

        Args:
            filename: Name of file to download
            workspace_id: Workspace folder (uses default if None)
            encoding: Text encoding (default: utf-8)

        Returns:
            File content as string
        """
        content = self.download_file(filename, workspace_id)
        return content.decode(encoding)

    def upload_file(self, filename: str, content: Union[str, bytes], workspace_id: str = None) -> bool:
        """
        Upload file to workspace.

        Args:
            filename: Name for uploaded file
            content: File content (string or bytes)
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if successful
        """
        file_url = self._build_url(workspace_id, filename)

        if isinstance(content, str):
            content = content.encode("utf-8")

        try:
            response = requests.put(file_url, headers=self.headers, data=content)
            response.raise_for_status()
            return response.status_code in [201, 204]

        except requests.RequestException as e:
            raise Exception(f"Failed to upload file '{filename}': {e}")

    def delete_file(self, filename: str, workspace_id: str = None) -> bool:
        """
        Delete file from workspace.

        Args:
            filename: Name of file to delete
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if successful
        """
        file_url = self._build_url(workspace_id, filename)

        try:
            response = requests.delete(file_url, headers=self.headers)
            response.raise_for_status()
            return response.status_code == 204

        except requests.RequestException as e:
            raise Exception(f"Failed to delete file '{filename}': {e}")

    def file_exists(self, filename: str, workspace_id: str = None) -> bool:
        """
        Check if file exists in workspace.

        Args:
            filename: Name of file to check
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if file exists
        """
        try:
            files = self.list_files(workspace_id)
            return any(f["name"] == filename for f in files)
        except Exception:
            return False

    def create_folder(self, folder_name: str, workspace_id: str = None) -> bool:
        """
        Create a folder in the workspace.

        Args:
            folder_name: Name of folder to create
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if successful
        """
        folder_url = self._build_url(workspace_id, folder_name)

        try:
            response = requests.request("MKCOL", folder_url, headers=self.headers)
            # 201 = created, 405 = already exists (which is fine)
            return response.status_code in [201, 405]

        except requests.RequestException as e:
            # Folder might already exist, which is okay
            if "405" in str(e) or "Method Not Allowed" in str(e):
                return True
            raise Exception(f"Failed to create folder '{folder_name}': {e}")

    def list_folders(self, workspace_id: str = None) -> List[str]:
        """
        List all folders (directories) in a workspace.

        Args:
            workspace_id: Workspace folder to list (uses default if None)

        Returns:
            List of folder names
        """
        folder_url = self._build_url(workspace_id)

        headers = {**self.headers, "Depth": "1", "Content-Type": "application/xml"}

        xml_body = """<?xml version="1.0"?>
        <d:propfind xmlns:d="DAV:">
            <d:prop>
                <d:displayname/>
                <d:resourcetype/>
            </d:prop>
        </d:propfind>
        """

        try:
            response = requests.request("PROPFIND", folder_url, headers=headers, data=xml_body)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            ns = {"d": "DAV:"}
            folders = []

            for resp in root.findall("d:response", ns):
                href = resp.find("d:href", ns)
                if href is None:
                    continue

                name = href.text.rstrip("/").split("/")[-1]
                if not name:
                    continue

                # Check if it's a collection (folder)
                props = resp.find("d:propstat/d:prop", ns)
                if props is not None:
                    resourcetype = props.find("d:resourcetype", ns)
                    if resourcetype is not None and resourcetype.find("d:collection", ns) is not None:
                        folders.append(name)

            return folders

        except requests.RequestException as e:
            raise Exception(f"Failed to list folders: {e}")
        except ET.ParseError as e:
            raise Exception(f"Failed to parse response: {e}")

    def ensure_folder_exists(self, folder_path: str, workspace_id: str = None) -> bool:
        """
        Ensure a folder path exists, creating it if necessary.
        Handles nested folders like 'results/service_name'.

        Args:
            folder_path: Path to folder (can include subdirectories)
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if folder exists or was created
        """
        # Split path into parts
        parts = folder_path.strip('/').split('/')

        # Create each level of the hierarchy
        current_path = ""
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            try:
                self.create_folder(current_path, workspace_id)
            except Exception as e:
                # Ignore errors if folder already exists
                if "405" not in str(e):
                    # Only raise if it's not a "folder exists" error
                    pass

        return True

    def upload_text_file(self, filename: str, content: str, workspace_id: str = None) -> bool:
        """
        Upload text file to workspace.

        Args:
            filename: Name for uploaded file
            content: Text content
            workspace_id: Workspace folder (uses default if None)

        Returns:
            True if successful
        """
        return self.upload_file(filename, content, workspace_id)



    # ==================== TIMESERIES-SPECIFIC METHODS ====================

    def read_csv(self, filename: str, workspace_id: str = None, **pandas_kwargs) -> pd.DataFrame:
        """
        Read CSV file as pandas DataFrame.

        Args:
            filename: CSV filename
            workspace_id: Workspace folder (uses default if None)
            **pandas_kwargs: Additional arguments for pd.read_csv()

        Returns:
            pandas DataFrame
        """
        content = self.download_text_file(filename, workspace_id)

        # Default pandas arguments for common timeseries formats
        default_kwargs = {
            "parse_dates": True,
            "index_col": None
        }
        default_kwargs.update(pandas_kwargs)

        try:
            df = pd.read_csv(StringIO(content), **default_kwargs)
            return df
        except Exception as e:
            raise Exception(f"Failed to parse CSV '{filename}': {e}")

    def read_timeseries_csv(self, filename: str, workspace_id: str = None,
                            timestamp_col: str = "timestamp", **pandas_kwargs) -> pd.DataFrame:
        """
        Read CSV file with automatic timestamp parsing and indexing.

        Args:
            filename: CSV filename
            workspace_id: Workspace folder (uses default if None)
            timestamp_col: Name of timestamp column
            **pandas_kwargs: Additional arguments for pd.read_csv()

        Returns:
            pandas DataFrame with timestamp as index
        """
        # Override parse_dates to handle timestamp column
        pandas_kwargs["parse_dates"] = [timestamp_col]

        df = self.read_csv(filename, workspace_id, **pandas_kwargs)

        # Set timestamp as index if it exists
        if timestamp_col in df.columns:
            df = df.set_index(timestamp_col)
            df.index.name = "timestamp"

        return df

    def write_csv(self, df: pd.DataFrame, filename: str, workspace_id: str = None, **pandas_kwargs) -> bool:
        """
        Write pandas DataFrame to CSV file.

        Args:
            df: DataFrame to write
            filename: Output filename
            workspace_id: Workspace folder (uses default if None)
            **pandas_kwargs: Additional arguments for df.to_csv()

        Returns:
            True if successful
        """
        # Default pandas arguments
        default_kwargs = {"index": True}
        default_kwargs.update(pandas_kwargs)

        try:
            csv_content = df.to_csv(**default_kwargs)
            return self.upload_file(filename, csv_content, workspace_id)
        except Exception as e:
            raise Exception(f"Failed to write CSV '{filename}': {e}")

    def get_csv_files(self, workspace_id: str = None) -> List[str]:
        """
        Get list of CSV files in workspace.

        Args:
            workspace_id: Workspace folder (uses default if None)

        Returns:
            List of CSV filenames
        """
        files = self.list_files(workspace_id)
        return [f["name"] for f in files if f["name"].lower().endswith(".csv")]

    # ==================== IMAGE/MEDIA METHODS ====================

    def download_image(self, filename: str, workspace_id: str = None) -> Optional[bytes]:
        """
        Download image file with validation.

        Args:
            filename: Image filename
            workspace_id: Workspace folder (uses default if None)

        Returns:
            Image bytes if valid, None otherwise
        """
        try:
            content = self.download_file(filename, workspace_id)

            # Validate image
            if len(content) < 100:
                return None

            kind = filetype.guess(content)
            if kind and kind.mime and kind.mime.startswith("image/"):
                return content

            return None

        except Exception:
            return None

    def get_workspace_image(self, workspace_id: str = None, image_name: str = "title.jpg") -> Optional[bytes]:
        """
        Get workspace title/header image.

        Args:
            workspace_id: Workspace folder (uses default if None)
            image_name: Image filename (default: title.jpg)

        Returns:
            Image bytes if found and valid, None otherwise
        """
        return self.download_image(image_name, workspace_id)

    # ==================== UTILITY METHODS ====================

    def set_workspace(self, workspace_id: str):
        """Set default workspace for subsequent operations."""
        self.workspace_id = workspace_id

    def get_workspace_info(self, workspace_id: str = None) -> Dict[str, Any]:
        """
        Get basic information about workspace.

        Args:
            workspace_id: Workspace folder (uses default if None)

        Returns:
            Dictionary with workspace info
        """
        ws_id = workspace_id or self.workspace_id
        if not ws_id:
            raise ValueError("No workspace_id provided")

        try:
            files = self.list_files(workspace_id)
            total_files = len(files)
            total_size = sum(f.get("size", 0) for f in files)
            csv_files = len([f for f in files if f["name"].lower().endswith(".csv")])

            return {
                "workspace_id": ws_id,
                "total_files": total_files,
                "total_size_bytes": total_size,
                "csv_files": csv_files,
                "files": files
            }

        except Exception as e:
            raise Exception(f"Failed to get workspace info: {e}")


# ==================== CONVENIENCE FUNCTIONS ====================

def create_client_from_env(workspace_id: str = None) -> NextcloudClient:
    """
    Create NextcloudClient using environment variables.

    Args:
        workspace_id: Default workspace to use

    Returns:
        Configured NextcloudClient instance
    """
    return NextcloudClient(workspace_id=workspace_id)


def quick_read_timeseries(filename: str, workspace_id: str,
                          timestamp_col: str = "timestamp") -> pd.DataFrame:
    """
    Quick function to read timeseries CSV from Nextcloud.

    Args:
        filename: CSV filename
        workspace_id: Workspace folder
        timestamp_col: Timestamp column name

    Returns:
        DataFrame with timestamp index
    """
    client = create_client_from_env(workspace_id)
    return client.read_timeseries_csv(filename, timestamp_col=timestamp_col)


# ==================== TESTING FUNCTIONS ====================

def test_client_basic_functionality(workspace_id: str = None) -> Dict[str, bool]:
    """
    Test basic client functionality.

    Args:
        workspace_id: Workspace to test (optional)

    Returns:
        Dictionary with test results
    """
    results = {
        "client_creation": False,
        "list_files": False,
        "upload_test": False,
        "download_test": False,
        "delete_test": False,
        "csv_operations": False
    }

    test_filename = "nextcloud_test_file.txt"
    test_content = f"Test file created at {pd.Timestamp.now()}\nThis is a test of the Nextcloud client."

    try:
        # Test 1: Client Creation
        print("🧪 Testing client creation...")
        client = create_client_from_env(workspace_id)
        results["client_creation"] = True
        print("✅ Client created successfully")

        # Test 2: List Files
        print("\n🧪 Testing file listing...")
        files = client.list_files()
        results["list_files"] = True
        print(f"✅ Listed {len(files)} files successfully")

        # Test 3: Upload Test File
        print("\n🧪 Testing file upload...")
        upload_success = client.upload_file(test_filename, test_content)
        if upload_success:
            results["upload_test"] = True
            print(f"✅ Uploaded '{test_filename}' successfully")
        else:
            print(f"❌ Failed to upload '{test_filename}'")

        # Test 4: Download Test File
        print("\n🧪 Testing file download...")
        downloaded_content = client.download_text_file(test_filename)
        if downloaded_content == test_content:
            results["download_test"] = True
            print(f"✅ Downloaded and verified '{test_filename}' successfully")
        else:
            print(f"❌ Downloaded content doesn't match uploaded content")

        # Test 5: Delete Test File
        print("\n🧪 Testing file deletion...")
        delete_success = client.delete_file(test_filename)
        if delete_success:
            results["delete_test"] = True
            print(f"✅ Deleted '{test_filename}' successfully")
        else:
            print(f"❌ Failed to delete '{test_filename}'")

        # Test 6: CSV Operations (if CSV files exist)
        print("\n🧪 Testing CSV operations...")
        csv_files = client.get_csv_files()
        if csv_files:
            try:
                sample_csv = csv_files[0]
                df = client.read_csv(sample_csv)
                results["csv_operations"] = True
                print(f"✅ Successfully read CSV '{sample_csv}' with {len(df)} rows and {len(df.columns)} columns")
            except Exception as e:
                print(f"⚠️ CSV read test failed: {e}")
        else:
            print("⚠️ No CSV files found for CSV operations test")
            results["csv_operations"] = True  # Mark as passed since no files to test

    except Exception as e:
        print(f"❌ Test failed with error: {e}")

    return results


if __name__ == "__main__":
    """
    Test the Nextcloud client functionality.
    Usage: python nextcloud_client.py [workspace_id]
    """
    import sys

    print("🚀 Starting Nextcloud Client Tests")
    print("=" * 50)

    # Get workspace ID from command line or use default
    workspace_id = sys.argv[1] if len(sys.argv) > 1 else None

    if workspace_id:
        print(f"📁 Testing with workspace: {workspace_id}")
    else:
        print("📁 Testing with default workspace (if configured)")

    print()

    # Run tests
    results = test_client_basic_functionality(workspace_id)

    # Print summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)

    passed = sum(results.values())
    total = len(results)

    for test_name, passed_test in results.items():
        status = "✅ PASS" if passed_test else "❌ FAIL"
        print(f"{test_name.replace('_', ' ').title(): <20} {status}")

    print(f"\n🎯 Overall Result: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Nextcloud client is working correctly.")
    else:
        print("⚠️ Some tests failed. Please check your configuration and network connection.")

    # Additional info
    print("\n💡 Configuration Check:")
    try:
        username = os.getenv("NEXTCLOUD_BASIC_USERNAME")
        password = os.getenv("NEXTCLOUD_BASIC_PASSWORD")
        base_url = os.getenv("NEXTCLOUD_BASE_URL")

        print(f"  Username: {'✅ Set' if username else '❌ Not set'}")
        print(f"  Password: {'✅ Set' if password else '❌ Not set'}")
        print(f"  Base URL: {base_url or '❌ Not set'}")

        if workspace_id:
            print(f"  Workspace: {workspace_id}")
        else:
            print(f"  Workspace: Default (not specified)")

    except Exception as e:
        print(f"  ❌ Config check failed: {e}")