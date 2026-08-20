# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker
# components/replica_builder/replica_excel_importer.py
"""
Excel Importer for Replica Builder — UI shell over the backend converter path.

There is ONE workbook parser: ``process_excel_to_ttl`` in
``backend/replica_builder/utils``. The session model is read back out of the
generated TTL via ``backend.replica_builder.excel_import`` (Phase 5 of the
backend/UI split) — the ~300-line duplicate spreadsheet parser this module
used to carry is gone. What stays here is the Streamlit wiring: the import
tab, template download, URI-config UI, and the workspace mirroring of the
uploaded workbook + converted TTL.
"""
import streamlit as st
from typing import Optional, Dict, List, Any
import tempfile
import os
import pandas as pd

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

from backend.replica_builder import excel_import as _excel_import

# Import NextCloud global client for template download
try:
    from components.nextcloud_global_client import get_global_nextcloud_client
    NEXTCLOUD_GLOBAL_AVAILABLE = True
except ImportError:
    NEXTCLOUD_GLOBAL_AVAILABLE = False


def _local_template_bytes() -> Optional[bytes]:
    """The vendored Excel template bytes, or None if not present locally.

    Candidates, in order: ``REPLICA_BUILDER_TEMPLATE_FILE`` (env override),
    the NextCloud-mirroring drop-in path
    ``data/global_replica_builder/replica_builder_template.xlsx``, and finally
    the canonical tracked workbook ``data/ingestion_template/
    data_ingestion_template.xlsx`` — so a fresh clone serves the template fully
    offline without duplicating the binary in the repo. Same pattern the
    service catalog uses for ``data/global_services``.
    """
    from pathlib import Path
    override = os.environ.get("REPLICA_BUILDER_TEMPLATE_FILE")
    candidates = [override] if override else [
        "data/global_replica_builder/replica_builder_template.xlsx",
        "data/ingestion_template/data_ingestion_template.xlsx",
    ]
    for candidate in candidates:
        try:
            p = Path(candidate)
            if p.is_file():
                return p.read_bytes()
        except Exception as e:
            print(f"[replica_builder] local template read skipped ({candidate}): {e}")
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
            "Expected the tracked template at `data/ingestion_template/data_ingestion_template.xlsx` "
            "(or a drop-in at `data/global_replica_builder/replica_builder_template.xlsx`, "
            "or set `REPLICA_BUILDER_TEMPLATE_FILE`), or enable NextCloud access."
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


def _workspace_default_units() -> Optional[Dict[str, str]]:
    """The ontology default-unit map for the active workspace, so the converter
    can stamp a unit onto any Physical/Geospatial attribute the workbook leaves
    blank — keeping the instance self-describing and constrained to the
    ontology. ``None`` when unavailable (never blocks the import)."""
    try:
        from backend.replica_builder.utils.default_units import load_workspace_default_units
        _ctx = st.session_state.get("workspace_context")
        if _ctx is not None:
            return load_workspace_default_units(storage=getattr(_ctx, "storage", None))
    except Exception as _e:  # never block the import on a lookup issue
        print(f"[replica-builder] default-unit map unavailable: {_e}")
    return None


def convert_excel_to_ttl_wrapper(uploaded_file, project_uri: str, uri_mode: str) -> tuple:
    """Wrapper that also returns parsed Excel data for session integration.

    The workbook is parsed ONCE, by ``process_excel_to_ttl`` (the authoritative
    converter); the session model is read back out of the generated TTL via
    ``backend.replica_builder.excel_import`` — so what the editor shows is
    exactly what the TTL says.

    Workspace-aware: if a WorkspaceContext is active in session state, the
    uploaded .xlsx is mirrored into the workspace's `ingestion/input/` and the
    converted .ttl is written to the workspace's `ingestion/output/`. This
    means a brand-new clone of the usecase repo always has the canonical
    input + output files version-controllable alongside everything else.
    """

    tmp_input_path = None

    try:
        # Save uploaded file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_input:
            tmp_input.write(uploaded_file.getvalue())
            tmp_input_path = tmp_input.name
        # File is now closed

        ttl_content, instances = _excel_import.import_workbook(
            tmp_input_path, project_uri, uri_mode,
            default_units=_workspace_default_units(),
        )
        excel_data = _excel_import.instances_payload(instances)

        # Persist input + output into the active workspace if one is selected.
        _save_to_active_workspace(uploaded_file, ttl_content)

        # Clean up temp file
        try:
            if tmp_input_path and os.path.exists(tmp_input_path):
                os.unlink(tmp_input_path)
        except Exception as e:
            print(f"Warning: Could not delete temp input file: {e}")

        return True, ttl_content, None, excel_data

    except Exception as e:
        # Clean up on error
        try:
            if tmp_input_path and os.path.exists(tmp_input_path):
                os.unlink(tmp_input_path)
        except:
            pass

        import traceback
        error_detail = traceback.format_exc()
        return False, "", f"Conversion error: {e}\n\nDetails:\n{error_detail}", None


def parse_excel_file(file_path: str, project_uri: str, uri_mode: str) -> Dict[str, Any]:
    """Parse an Excel workbook into the session instance shape.

    Delegates to the backend converter path (``process_excel_to_ttl`` →
    TTL parse-back): the authoritative parser runs once and the session model
    is exactly the generated TTL's content. Kept for callers of the old name.
    """
    _, instances = _excel_import.import_workbook(
        file_path, project_uri, uri_mode,
        default_units=_workspace_default_units(),
    )
    return _excel_import.instances_payload(instances)


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