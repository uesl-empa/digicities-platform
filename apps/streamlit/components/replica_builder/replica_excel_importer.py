# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_excel_importer.py
"""
Excel Importer for Replica Builder
Converts Excel templates to TTL and integrates instances into session state.
"""
import streamlit as st
from typing import Optional, Dict, List, Any
import tempfile
import os
import pandas as pd
import re

def _save_to_active_workspace(uploaded_file, ttl_content: str) -> None:
    """If a workspace is active, mirror the upload + conversion into its
    canonical `ingestion/input/` and `ingestion/output/` dirs.

    Silent no-op when no workspace is active or storage write fails — keeps
    the Replica Builder usable in non-workspace contexts.
    """
    try:
        import streamlit as _st
        ctx = _st.session_state.get("workspace_context")
        if ctx is None:
            return
        base = uploaded_file.name or "upload.xlsx"
        if base.lower().endswith((".xlsx", ".xls")):
            stem = base.rsplit(".", 1)[0]
        else:
            stem = base
        ctx.storage.write_bytes(f"ingestion/input/{base}", uploaded_file.getvalue())
        ctx.storage.write_text(f"ingestion/output/{stem}.ttl", ttl_content)
    except Exception as e:
        print(f"[replica_builder] workspace mirror skipped: {e}")


# process_excel_to_ttl lives in the utils module — import it here so callers
# of this module can reach it without caring about the underlying location.
from backend.replica_builder.utils.create_class_and_attribute_graph import process_excel_to_ttl  # noqa: F401

# Import NextCloud global client for template download
try:
    from components.nextcloud_global_client import get_global_nextcloud_client
    NEXTCLOUD_GLOBAL_AVAILABLE = True
except ImportError:
    NEXTCLOUD_GLOBAL_AVAILABLE = False


def _local_template_bytes() -> Optional[bytes]:
    """The vendored Excel template bytes, or None if not present locally.

    Path from ``REPLICA_BUILDER_TEMPLATE_FILE`` (default
    ``data/global_replica_builder/replica_builder_template.xlsx``). This is the
    local counterpart to the NextCloud ``global/replica_builder/...`` template, so
    the template works without NextCloud — the same pattern the service catalog
    uses for ``data/global_services``.
    """
    from pathlib import Path
    candidate = os.environ.get(
        "REPLICA_BUILDER_TEMPLATE_FILE",
        "data/global_replica_builder/replica_builder_template.xlsx",
    )
    try:
        p = Path(candidate)
        if p.is_file():
            return p.read_bytes()
    except Exception as e:
        print(f"[replica_builder] local template read skipped: {e}")
    return None


def _offer_template_download(template_data: bytes) -> None:
    st.success("✅ Template ready!")
    st.download_button(
        label="💾 Save Template",
        data=template_data,
        file_name="replica_builder_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.info("👆 Click 'Save Template' to download the file to your computer.")


def download_excel_template():
    """Offer the Excel template for download — local vendored copy first, then
    the NextCloud global directory as a fallback."""
    # 1. Local vendored template (works without NextCloud).
    local_bytes = _local_template_bytes()
    if local_bytes is not None:
        _offer_template_download(local_bytes)
        return

    # 2. NextCloud global directory fallback.
    if not NEXTCLOUD_GLOBAL_AVAILABLE:
        st.error("❌ No local template found and NextCloud is not available.")
        st.info(
            "Add a template at `data/global_replica_builder/replica_builder_template.xlsx` "
            "(or set `REPLICA_BUILDER_TEMPLATE_FILE`), or enable NextCloud access."
        )
        return

    try:
        # Create global NextCloud client
        global_client = get_global_nextcloud_client()
        if not global_client:
            st.error("❌ Could not connect to NextCloud. Please check your credentials.")
            return

        # Template file path in global directory
        template_path = "replica_builder/replica_builder_template.xlsx"

        with st.spinner("📥 Downloading template from NextCloud..."):
            # Download the template bytes over WebDAV.
            try:
                file_url = f"{global_client.base_url}/remote.php/dav/files/{global_client.username}/global/{template_path}"

                import requests
                response = requests.get(
                    file_url,
                    auth=(global_client.username, global_client.password),
                    timeout=30
                )

                if response.status_code == 200:
                    _offer_template_download(response.content)

                else:
                    st.error(f"❌ Failed to download template. HTTP {response.status_code}")
                    st.info(f"Template location: `global/{template_path}`")
                    st.caption("Please ensure the template file exists in the NextCloud global directory.")

            except Exception as download_error:
                st.error(f"❌ Error downloading template: {download_error}")
                st.info(f"Looking for: `global/{template_path}`")

    except Exception as e:
        st.error(f"❌ Error accessing NextCloud: {e}")
        import traceback
        with st.expander("🐛 Error Details"):
            st.code(traceback.format_exc())


def tab_excel_import():
    """Tab for importing instances from Excel file"""
    st.subheader("Excel Import (Legacy)")

    st.write("""
    Import component instances from an Excel file using the legacy format.
    This uses the exact `process_excel_to_ttl` function logic with full backwards compatibility.
    **Imported instances will be automatically added to your session and appear in all tabs.**
    """)

    # Template download section
    st.write("### 📥 Download Excel Template")
    col1, col2 = st.columns([3, 1])

    with col1:
        st.info("📄 Download the standard Excel template to see the required structure for importing instances.")

    with col2:
        if st.button("📥 Get Template", type="primary", use_container_width=True):
            download_excel_template()

    st.markdown("---")

    # File upload
    st.write("### Upload Excel File")

    uploaded_file = st.file_uploader(
        "Choose Excel file",
        type=['xlsx', 'xls'],
        help="Upload Excel file with component instances",
        key="excel_file_uploader"
    )

    if uploaded_file is not None:
        # URI Configuration - shown per upload
        with st.expander("⚙️ URI Generation Settings", expanded=True):
            render_excel_import_config()

        render_excel_preview_and_convert(uploaded_file)


def render_excel_import_config():
    """Render configuration for Excel import"""

    st.write("**URI Generation Configuration**")
    st.caption("⚙️ Configure how URIs are generated from your Excel file. Change these settings and reconvert to see different results.")

    col1, col2 = st.columns(2)

    with col1:
        project_uri = st.text_input(
            "Project URI (for Excel)",
            value=st.session_state.replica_project_uri,
            help="Base URI for instances imported from Excel",
            key="excel_project_uri"
        )

        if project_uri != st.session_state.replica_project_uri:
            st.session_state.replica_project_uri = project_uri

    with col2:
        uri_modes = {
            "default": "Default (project/sheet/id)",
            "full-uri-in-cell": "Full URI in cell",
            "complete-project-uri": "Complete URI (project#id)"
        }

        uri_mode = st.selectbox(
            "URI Generation Mode",
            options=list(uri_modes.keys()),
            format_func=lambda x: uri_modes[x],
            index=list(uri_modes.keys()).index(st.session_state.replica_uri_mode),
            help="How to generate URIs from Excel cell values",
            key="excel_uri_mode"
        )

        if uri_mode != st.session_state.replica_uri_mode:
            st.session_state.replica_uri_mode = uri_mode

    # Show URI examples specific to Excel
    st.write("---")
    if st.checkbox("Show Excel URI Generation Examples", key="show_excel_uri_examples"):
        st.write("**How URIs are generated from Excel based on mode:**")

        example_cell_value = "http://ait.ac.at/NMS_Enkplatz#H39"
        example_sheet = "ThermalEnergyGenerator"

        st.write(f"**Example:** Excel cell contains `{example_cell_value}`")
        st.write(f"**Sheet name:** `{example_sheet}`")
        st.write(f"**Project URI:** `{st.session_state.replica_project_uri}`")

        st.write("")

        if st.session_state.replica_uri_mode == "default":
            result = f"{st.session_state.replica_project_uri}/{example_sheet}/{example_cell_value}"
            st.code(result)
            st.caption("Mode: Default - Appends sheet name and cell value to project URI")

        elif st.session_state.replica_uri_mode == "full-uri-in-cell":
            result = example_cell_value
            st.code(result)
            st.caption("Mode: Full URI - Uses the cell value as-is (ignores project URI)")

        elif st.session_state.replica_uri_mode == "complete-project-uri":
            fragment = example_cell_value.split('#')[-1] if '#' in example_cell_value else example_cell_value
            result = f"{st.session_state.replica_project_uri}#{fragment}"
            st.code(result)
            st.caption("Mode: Complete Project URI - Extracts fragment from cell and appends to project URI")

    st.write("---")
    if st.checkbox("Show Expected Excel Format", key="show_excel_format"):
        st.write("""
        **Excel Structure:**
        - Multiple sheets, each representing a component type
        - First column named 'id' with unique identifiers
        - Subsequent columns for attributes with flexible header rows (1-6 rows supported):
          - Row 0: Attribute name (required)
          - Row 1: Attribute type (optional - Physical, Dynamic, Categorical, Event, etc.)
          - Row 2: Unit (optional - for Physical/Dynamic attributes)
          - Row 3: Unit Y (optional - for Curve attributes)
          - Row 4: Currency (optional - for Cost attributes)
          - Row 5: Predicate (optional - for ClassObject attributes)

        **Supported Attribute Types:**
        Physical, Dynamic (Historic/Live/Future), Categorical, Event, SimpleCost, 
        UnitBasedCost, Curve, Resource, SimpleValue, CustomPhysicalRatio, 
        Identifier, ClassObject, Annotation

        **Note:** The system automatically detects the number of header rows (1-6).
        Your current template with 5 header rows will work perfectly!
        """)


def render_excel_preview_and_convert(uploaded_file):
    """Preview Excel and convert to TTL"""

    st.write("### Excel File Preview")

    try:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_names = excel_file.sheet_names

        component_sheets = [s for s in sheet_names if s != "Data Validation"]

        st.info(f"Found {len(component_sheets)} component sheet(s): {', '.join(component_sheets)}")

        # Detect header rows for preview
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        try:
            # Detect headers
            def detect_preview_headers(file_path, sheet_name):
                for num_headers in [5, 4, 3, 2, 1, 6]:
                    try:
                        header_list = list(range(num_headers))
                        test_df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_list, nrows=2)
                        if len(test_df.columns) > 0:
                            first_col = test_df.columns[0]
                            if isinstance(first_col, tuple):
                                col_name = first_col[0]
                            else:
                                col_name = first_col
                            if col_name == 'id':
                                return header_list
                    except:
                        continue
                return [0]

            first_sheet = component_sheets[0]
            header_rows = detect_preview_headers(tmp_path, first_sheet)
            st.caption(f"Detected {len(header_rows)} header row(s)")

            with st.expander("Preview Sheets", expanded=False):
                for sheet_name in component_sheets:
                    st.write(f"**{sheet_name}**")
                    df = pd.read_excel(tmp_path, sheet_name=sheet_name, header=header_rows)
                    st.dataframe(df.head(), use_container_width=True)
        finally:
            os.unlink(tmp_path)

        st.write("---")

        # Step 1: Convert to TTL
        if 'excel_converted_data' not in st.session_state:
            st.session_state.excel_converted_data = None
        if 'excel_last_uri_mode' not in st.session_state:
            st.session_state.excel_last_uri_mode = None
        if 'excel_last_project_uri' not in st.session_state:
            st.session_state.excel_last_project_uri = None

        # Check if URI settings changed - if so, clear previous conversion
        settings_changed = False
        if st.session_state.excel_converted_data is not None:
            if st.session_state.excel_last_uri_mode != st.session_state.replica_uri_mode:
                settings_changed = True
                st.info("🔄 URI mode changed. Reconversion required.")
            if st.session_state.excel_last_project_uri != st.session_state.replica_project_uri:
                settings_changed = True
                st.info("🔄 Project URI changed. Reconversion required.")

        if settings_changed:
            st.session_state.excel_converted_data = None

        if st.session_state.excel_converted_data is None:
            # Not yet converted
            if st.button("Convert Excel to TTL", type="primary", use_container_width=True, key="convert_excel_button"):
                with st.spinner("Converting Excel to TTL..."):
                    success, ttl_content, error_msg, excel_data = convert_excel_to_ttl_wrapper(
                        uploaded_file,
                        st.session_state.replica_project_uri,
                        st.session_state.replica_uri_mode
                    )

                    if success and excel_data:
                        # Store converted data in session state
                        st.session_state.excel_converted_data = {
                            'ttl_content': ttl_content,
                            'excel_data': excel_data,
                            'instance_count': len(excel_data['instances'])
                        }
                        # Store the settings used for this conversion
                        st.session_state.excel_last_uri_mode = st.session_state.replica_uri_mode
                        st.session_state.excel_last_project_uri = st.session_state.replica_project_uri
                        st.rerun()
                    else:
                        st.error(f"Conversion failed: {error_msg}")

        else:
            # Already converted - show preview and import options
            st.success(f"✅ Conversion successful! Found {st.session_state.excel_converted_data['instance_count']} instances")

            # Show which settings were used for conversion
            uri_modes = {
                "default": "Default (project/sheet/id)",
                "full-uri-in-cell": "Full URI in cell",
                "complete-project-uri": "Complete URI (project#id)"
            }
            current_mode = st.session_state.excel_last_uri_mode or "default"
            current_project_uri = st.session_state.excel_last_project_uri or st.session_state.replica_project_uri

            col1, col2 = st.columns(2)
            with col1:
                st.info(f"📐 **URI Mode:** {uri_modes.get(current_mode, current_mode)}")
            with col2:
                st.info(f"🔗 **Project URI:** `{current_project_uri}`")

            st.caption("💡 Tip: Change settings in '⚙️ URI Generation Settings' above and click '🔄 Reconvert' below to see different results")

            # Show TTL preview
            st.write("### Generated TTL Preview")

            with st.expander("View Complete TTL", expanded=False):
                st.code(st.session_state.excel_converted_data['ttl_content'], language="turtle")

            # Show summary
            st.write("### Import Summary")

            # Count instances by type
            instances_by_type = {}
            for inst in st.session_state.excel_converted_data['excel_data']['instances']:
                comp_type = inst['component_type']
                if comp_type not in instances_by_type:
                    instances_by_type[comp_type] = []
                instances_by_type[comp_type].append(inst['id'])

            col1, col2 = st.columns([1, 2])

            with col1:
                st.metric("Total Instances", st.session_state.excel_converted_data['instance_count'])
                st.metric("Component Types", len(instances_by_type))

            with col2:
                st.write("**Instances by Type:**")
                for comp_type, inst_ids in sorted(instances_by_type.items()):
                    st.write(f"- **{comp_type}**: {len(inst_ids)} instances")

            # Download option
            st.download_button(
                "📥 Download TTL File",
                data=st.session_state.excel_converted_data['ttl_content'],
                file_name="excel_import.ttl",
                mime="text/turtle",
                use_container_width=True
            )

            st.write("---")

            # Import options
            st.write("### Import to Session")

            col1, col2 = st.columns(2)

            with col1:
                conversion_mode = st.radio(
                    "Import Mode",
                    ["Add to Current Session", "Replace Current Session"],
                    help="Choose how to handle the converted instances"
                )

            with col2:
                st.write("")
                st.write("")
                if st.button("🚀 Import to Session", type="primary", use_container_width=True):
                    # Handle conversion mode
                    if conversion_mode == "Replace Current Session":
                        st.session_state.replica_instances = []
                        st.session_state.replica_links = []

                    # Add to session
                    added_count = parse_excel_and_add_to_session(
                        st.session_state.excel_converted_data['excel_data'],
                        st.session_state.excel_converted_data['ttl_content']
                    )

                    if added_count > 0:
                        st.success(f"✅ Successfully imported {added_count} instances with all attributes!")

                        # Clear converted data
                        st.session_state.excel_converted_data = None

                        # Force rerun to show instances in other tabs
                        st.rerun()
                    else:
                        st.warning("No new instances were added (they may already exist)")

                if st.button("🔄 Reconvert with Different Settings", use_container_width=True):
                    # Clear conversion to allow re-conversion with new settings
                    st.session_state.excel_converted_data = None
                    st.rerun()

    except Exception as e:
        st.error(f"Error reading Excel file: {e}")
        import traceback
        st.code(traceback.format_exc())


def convert_excel_to_ttl_wrapper(uploaded_file, project_uri: str, uri_mode: str) -> tuple:
    """Wrapper that also returns parsed Excel data for session integration.

    Workspace-aware: if a WorkspaceContext is active in session state, the
    uploaded .xlsx is mirrored into the workspace's `ingestion/input/` and the
    converted .ttl is written to the workspace's `ingestion/output/`. This
    means a brand-new clone of the usecase repo always has the canonical
    input + output files version-controllable alongside everything else.
    """

    tmp_input_path = None
    tmp_output_path = None

    try:
        # Save uploaded file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_input:
            tmp_input.write(uploaded_file.getvalue())
            tmp_input_path = tmp_input.name
        # File is now closed

        # Parse Excel directly for session data
        excel_data = parse_excel_file(tmp_input_path, project_uri, uri_mode)

        # Create output file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ttl', mode='w') as tmp_output:
            tmp_output_path = tmp_output.name
        # File is now closed

        # Call the embedded function
        process_excel_to_ttl(
            project_uri=project_uri,
            file_path=tmp_input_path,
            output_ttl_path=tmp_output_path,
            uri_mode=uri_mode
        )

        # Read TTL content
        with open(tmp_output_path, 'r', encoding='utf-8') as f:
            ttl_content = f.read()

        # Persist input + output into the active workspace if one is selected.
        _save_to_active_workspace(uploaded_file, ttl_content)

        # Clean up temp files
        try:
            if tmp_input_path and os.path.exists(tmp_input_path):
                os.unlink(tmp_input_path)
        except Exception as e:
            print(f"Warning: Could not delete temp input file: {e}")

        try:
            if tmp_output_path and os.path.exists(tmp_output_path):
                os.unlink(tmp_output_path)
        except Exception as e:
            print(f"Warning: Could not delete temp output file: {e}")

        return True, ttl_content, None, excel_data

    except Exception as e:
        # Clean up on error
        try:
            if tmp_input_path and os.path.exists(tmp_input_path):
                os.unlink(tmp_input_path)
        except:
            pass

        try:
            if tmp_output_path and os.path.exists(tmp_output_path):
                os.unlink(tmp_output_path)
        except:
            pass

        import traceback
        error_detail = traceback.format_exc()
        return False, "", f"Conversion error: {e}\n\nDetails:\n{error_detail}", None


def parse_excel_file(file_path: str, project_uri: str, uri_mode: str) -> Dict[str, Any]:
    """
    Parse Excel file and extract instance data with attributes
    Returns structured data for adding to session
    UPDATED: Flexible header detection + proper URI handling
    """

    def is_nonempty(val):
        if pd.isna(val):
            return False
        if isinstance(val, str):
            s = val.strip().lower()
            if s == "" or s == "na":
                return False
        return True

    def detect_header_rows(file_path, sheet_name):
        """Detect number of header rows"""
        for num_headers in [5, 4, 3, 2, 1, 6]:
            try:
                header_list = list(range(num_headers))
                test_df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_list, nrows=2)

                if len(test_df.columns) > 0:
                    first_col = test_df.columns[0]
                    if isinstance(first_col, tuple):
                        col_name = first_col[0]
                    else:
                        col_name = first_col

                    if col_name == 'id':
                        return header_list
            except:
                continue

        return [0]

    def generate_instance_uri(project_uri, sheet_name, row_id, uri_mode):
        """Generate instance URI based on mode - must match TTL generation exactly"""
        row_id_str = str(row_id).strip()

        if uri_mode == "default":
            # Default: project_uri/sheet_name/id
            return f"{project_uri}/{sheet_name}/{row_id_str}"

        elif uri_mode == "full-uri-in-cell":
            # Full URI mode: the cell contains the complete URI
            # Don't add project_uri, just use what's in the cell
            return row_id_str

        elif uri_mode == "complete-project-uri":
            # Complete project URI: project_uri#id
            # The cell might contain the full URI or just the fragment
            if row_id_str.startswith('http://') or row_id_str.startswith('https://'):
                # Cell contains full URI, extract just the fragment after #
                if '#' in row_id_str:
                    fragment = row_id_str.split('#')[-1]
                    return f"{project_uri}#{fragment}"
                else:
                    # No fragment, use the whole thing as fragment
                    return f"{project_uri}#{row_id_str}"
            else:
                # Cell contains just the ID/fragment
                return f"{project_uri}#{row_id_str}"

        else:
            # Fallback to default
            return f"{project_uri}/{sheet_name}/{row_id_str}"

    # Detect header structure
    excel_file = pd.ExcelFile(file_path)
    first_sheet = [s for s in excel_file.sheet_names if s != "Data Validation"][0]
    header_rows = detect_header_rows(file_path, first_sheet)

    # Read with detected headers
    sheets = pd.read_excel(file_path, sheet_name=None, header=header_rows)

    instances_data = []

    for sheet_name, df in sheets.items():
        if sheet_name == "Data Validation":
            continue

        # Find id column
        id_col = None
        for col in df.columns:
            if isinstance(col, tuple):
                col_name = col[0]
            else:
                col_name = col

            if col_name == "id":
                id_col = col
                break
        if id_col is None:
            continue

        # Process each row
        for _, row in df.iterrows():
            row_id = row[id_col]
            if not is_nonempty(row_id):
                continue

            # Generate URI using the same logic as TTL generation
            instance_uri = generate_instance_uri(project_uri, sheet_name, row_id, uri_mode)

            # For label, extract just the ID part
            row_id_str = str(row_id).strip()

            # Extract clean label based on mode
            if uri_mode == "complete-project-uri" or uri_mode == "full-uri-in-cell":
                # If the cell contains a full URI, extract the fragment/last part for label
                if '#' in row_id_str:
                    label = row_id_str.split('#')[-1]
                elif '/' in row_id_str:
                    label = row_id_str.split('/')[-1]
                else:
                    label = row_id_str
            else:
                # Default mode: use the ID as-is
                label = row_id_str

            instance_data = {
                'id': row_id_str,  # Keep original ID for uniqueness check
                'component_type': sheet_name,
                'uri': instance_uri,
                'label': label,
                'attributes': {},
                'annotations': {},
                'class_objects': {}  # predicate: target_uri
            }

            # Parse attributes
            for col in df.columns:
                if isinstance(col, tuple):
                    col_name = col[0]
                    attr_type = col[1] if len(col) > 1 else None
                    qudt_unit = col[2] if len(col) > 2 and is_nonempty(col[2]) else None
                    qudt_unit_y = col[3] if len(col) > 3 and is_nonempty(col[3]) else None
                    currency = col[4] if len(col) > 4 and is_nonempty(col[4]) else None
                    predicate = col[5] if len(col) > 5 and is_nonempty(col[5]) else None
                else:
                    col_name = col
                    attr_type = None
                    qudt_unit = None
                    qudt_unit_y = None
                    currency = None
                    predicate = None

                if col_name == "id" or col_name.endswith("_datasource"):
                    continue

                if attr_type:
                    attr_type = attr_type.strip().replace(" ", "")

                value = row[col]
                if not is_nonempty(value):
                    continue

                # Handle different attribute types
                if attr_type == "Annotation":
                    instance_data['annotations'][col_name] = str(value).strip()
                    continue

                elif attr_type == "ClassObject":
                    # Handle ClassObject - creates direct predicate relationships
                    if predicate and is_nonempty(predicate):
                        # Generate target URI based on mode
                        if uri_mode == "default":
                            target_uri = f"{project_uri}/{str(value).strip()}"
                        elif uri_mode == "full-uri-in-cell":
                            target_uri = str(value).strip()
                        elif uri_mode == "complete-project-uri":
                            target_uri = f"{project_uri}{str(value).strip()}"
                        else:
                            target_uri = f"{project_uri}/{str(value).strip()}"

                        instance_data['class_objects'][predicate] = target_uri
                    continue

                # Get datasource if exists
                ds_col = next((c for c in df.columns if (isinstance(c, tuple) and c[0] == f"{col_name}_datasource") or c == f"{col_name}_datasource"), None)
                datasource = None
                if ds_col and is_nonempty(row[ds_col]):
                    datasource = row[ds_col]

                # Build attribute data
                attr_data = {'type': attr_type or 'Physical'}

                if attr_type in ["Historic", "Live", "Future"]:
                    attr_data = {
                        'type': 'Dynamic',
                        'time_series_type': attr_type,
                        'reference': str(value),
                        'unit': qudt_unit
                    }
                elif attr_type == "Physical":
                    try:
                        numeric_value = float(value)
                    except:
                        numeric_value = str(value)

                    attr_data = {
                        'type': 'Physical',
                        'value': numeric_value,
                        'unit': qudt_unit or ''
                    }
                elif attr_type == "Categorical":
                    attr_data = {
                        'type': 'Categorical',
                        'category_value': str(value).strip()
                    }
                elif attr_type == "Event":
                    # Determine precision from value
                    value_str = str(value).strip()
                    try:
                        float_val = float(value_str)
                        if float_val.is_integer() and 1000 <= float_val <= 9999:
                            value_str = str(int(float_val))
                    except:
                        pass

                    precision = "Year"
                    if re.match(r'^\d{4}$', value_str):
                        precision = "Year"
                    elif re.match(r'^\d{4}-\d{2}$', value_str) or re.match(r'^\d{2}\.\d{4}$', value_str):
                        precision = "YearMonth"
                    elif 'T' in value_str or ':' in value_str:
                        precision = "DateTime"
                    else:
                        precision = "Date"

                    attr_data = {
                        'type': 'Event',
                        'temporal_value': value_str,
                        'temporal_precision': precision
                    }
                elif attr_type in ["SimpleCost", "UnitBasedCost"]:
                    try:
                        numeric_value = float(value)
                    except:
                        numeric_value = 0.0

                    attr_data = {
                        'type': attr_type,
                        'value': numeric_value,
                        'currency': currency or 'CHF'
                    }
                    if attr_type == "UnitBasedCost":
                        attr_data['unit'] = qudt_unit or ''
                elif attr_type == "Curve":
                    attr_data = {
                        'type': 'Curve',
                        'data_points': str(value),
                        'x_unit': qudt_unit or '',
                        'y_unit': qudt_unit_y or ''
                    }
                elif attr_type == "Resource":
                    attr_data = {
                        'type': 'Resource',
                        'data_path': str(value).strip()
                    }
                elif attr_type == "SimpleValue":
                    attr_data = {
                        'type': 'SimpleValue',
                        'value': str(value)
                    }
                elif attr_type == "CustomPhysicalRatio":
                    custom_unit = ""
                    if qudt_unit and qudt_unit_y:
                        custom_unit = f"{qudt_unit}/{qudt_unit_y}"
                    elif qudt_unit:
                        custom_unit = qudt_unit
                    elif qudt_unit_y:
                        custom_unit = f"1/{qudt_unit_y}"

                    try:
                        numeric_value = float(value)
                    except:
                        numeric_value = 0.0

                    attr_data = {
                        'type': 'CustomPhysicalRatio',
                        'value': numeric_value,
                        'custom_unit': custom_unit
                    }
                elif attr_type == "Identifier":
                    attr_data = {
                        'type': 'Identifier',
                        'identifier_value': str(value).strip()
                    }
                else:
                    # Default to Physical
                    try:
                        numeric_value = float(value)
                    except:
                        numeric_value = str(value)

                    attr_data = {
                        'type': 'Physical',
                        'value': numeric_value,
                        'unit': qudt_unit or ''
                    }

                if datasource:
                    attr_data['datasource'] = datasource

                instance_data['attributes'][col_name] = attr_data

            instances_data.append(instance_data)

    return {'instances': instances_data}


def parse_excel_and_add_to_session(excel_data: Dict[str, Any], ttl_content: str) -> int:
    """
    Parse Excel data and add fully configured instances to session
    Returns count of added instances
    """

    try:
        from components.replica_builder.replica_instance_manager import ComponentInstance

        added_count = 0

        # O(1) membership instead of scanning the growing list per instance
        # (that was O(n^2) and hung the UI on large workbooks).
        existing_ids = {inst.id for inst in st.session_state.replica_instances}

        for inst_data in excel_data['instances']:
            if inst_data['id'] in existing_ids:
                continue
            # Create instance with all data
            instance = ComponentInstance(
                id=inst_data['id'],
                component_type=inst_data['component_type'],
                uri=inst_data['uri'],
                label=inst_data['label'],
                attributes=inst_data['attributes'],
                annotations=inst_data['annotations'],
                class_objects=inst_data.get('class_objects', {})
            )

            st.session_state.replica_instances.append(instance)
            existing_ids.add(inst_data['id'])
            added_count += 1

        return added_count

    except Exception as e:
        st.error(f"Error adding instances to session: {e}")
        import traceback
        st.code(traceback.format_exc())
        return 0