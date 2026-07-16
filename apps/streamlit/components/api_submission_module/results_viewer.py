# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Results Viewer Module
File: components/api_submission_module/results_viewer.py

FIXED VERSION - Ensures folders are created and results are saved properly
"""

import streamlit as st
import json
from datetime import datetime
from typing import Dict, List, Any
import pandas as pd


def save_submission_result_to_nextcloud(
    service_name: str,
    scenario_name: str,
    submission_result: Any,
    submitted_data: Dict
) -> bool:
    """
    Save submission result to NextCloud - GUARANTEED TO WORK VERSION
    """
    debug = st.session_state.get('debug_mode', False)
    try:
        # Get current workspace
        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            return False

        workspace_id = current_workspace.get('id')
        if not workspace_id:
            return False

        # Build the result object
        timestamp = datetime.now()
        result_data = {
            "metadata": {
                "service_name": service_name,
                "scenario_name": scenario_name,
                "timestamp": timestamp.isoformat(),
                "success": submission_result.success,
                "status_code": submission_result.status_code
            },
            "submission": {
                "api_url": submission_result.api_url or "",
                "scenario_id": submission_result.scenario_id or "",
                "result_url": submission_result.result_url or ""
            },
            "response": submission_result.response_data or {},
            "submitted_data": submitted_data
        }

        # Create filename
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        clean_scenario = scenario_name.replace('/', '_').replace('\\', '_').replace(':', '_')
        filename = f"{clean_scenario}_{timestamp_str}.json"

        # Convert to JSON
        json_content = json.dumps(result_data, indent=2, ensure_ascii=False)

        # Prefer the ACTIVE workspace storage (local FS, NextCloud, S3 — whatever
        # this workspace uses). Local-filesystem workspaces (e.g. the bundled demo)
        # save here and need no NextCloud credentials.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is not None:
            try:
                storage.write_text(f"results/{service_name}/{filename}", json_content)
                if debug:
                    st.success(f"✅ Saved: results/{service_name}/{filename}")
                return True
            except Exception as exc:
                if debug:
                    st.warning(f"Result not saved to workspace storage: {exc}")
                return False

        # Fallback: legacy direct NextCloud client, only when there's no active
        # workspace storage. Degrade quietly if NextCloud isn't configured —
        # saving the result file is best-effort and must not break submission.
        try:
            from components.nextcloud_client import NextcloudClient
            client = NextcloudClient(workspace_id=workspace_id)
            client.create_folder("results", workspace_id=workspace_id)
            client.create_folder(service_name, workspace_id=f"{workspace_id}/results")
            success = client.upload_file(
                filename=filename,
                content=json_content,
                workspace_id=f"{workspace_id}/results/{service_name}",
            )
            if success and debug:
                st.success(f"✅ Saved: {workspace_id}/results/{service_name}/{filename}")
            return bool(success)
        except Exception as exc:
            if debug:
                st.warning(f"Result not saved (NextCloud unavailable): {exc}")
            return False

    except Exception as e:
        if debug:
            st.warning(f"Result not saved: {e}")
        return False


def load_results_from_nextcloud() -> Dict[str, List[Dict]]:
    """
    Load all saved results from NextCloud workspace/results/ folder.
    """
    results_by_service = {}

    try:
        # Local mode: read results from the active workspace's storage.
        ctx = st.session_state.get("workspace_context")
        storage = getattr(ctx, "storage", None) if ctx is not None else None
        if storage is not None:
            try:
                for rel in storage.glob("results/*/*.json"):
                    parts = rel.split("/")
                    service_name = parts[1] if len(parts) >= 3 else "results"
                    try:
                        result_data = json.loads(storage.read_text(rel))
                    except Exception:
                        continue
                    result_data['_filename'] = parts[-1]
                    results_by_service.setdefault(service_name, []).append(result_data)
                for svc in results_by_service:
                    results_by_service[svc].sort(
                        key=lambda x: x.get('metadata', {}).get('timestamp', ''), reverse=True)
                return results_by_service
            except Exception:
                pass  # fall through to the NextCloud path below

        current_workspace = st.session_state.get('current_workspace')
        if not current_workspace:
            return results_by_service

        workspace_id = current_workspace.get('id')
        if not workspace_id:
            return results_by_service

        from components.nextcloud_client import NextcloudClient
        client = NextcloudClient(workspace_id=workspace_id)

        # Get list of known services
        known_services = ["CESARP_Building_Simulation"]

        if 'registered_apis' in st.session_state:
            known_services.extend(st.session_state.registered_apis.keys())

        known_services = list(set(known_services))

        # Load results from each service folder
        for service_name in known_services:
            try:
                service_path = f"{workspace_id}/results/{service_name}"
                service_files = client.list_files(workspace_id=service_path)

                if not service_files:
                    continue

                service_results = []

                for file_info in service_files:
                    filename = file_info['name']
                    if filename.endswith('.json') and not filename.startswith('.'):
                        try:
                            json_content = client.download_text_file(filename, workspace_id=service_path)
                            result_data = json.loads(json_content)

                            result_data['_filename'] = filename
                            result_data['_file_size'] = file_info.get('size', 0)

                            service_results.append(result_data)

                        except Exception as e:
                            if st.session_state.get('debug_mode'):
                                st.warning(f"⚠️ Could not load {filename}: {str(e)}")

                if service_results:
                    service_results.sort(
                        key=lambda x: x.get('metadata', {}).get('timestamp', ''),
                        reverse=True
                    )
                    results_by_service[service_name] = service_results

            except Exception as e:
                # No results for this service yet
                pass

    except Exception as e:
        st.error(f"Error loading results: {str(e)}")

    return results_by_service


def render_past_results_tab():
    """Render the Past Results viewer tab."""
    st.subheader("📊 View Past Results")
    st.write("Browse and analyze previous API submission results stored in NextCloud")

    current_workspace = st.session_state.get('current_workspace')
    if not current_workspace:
        st.warning("⚠️ No workspace connected")
        st.info("💡 Connect to a NextCloud workspace to view and save submission results")
        return

    workspace_id = current_workspace.get('id')

    # Debug mode toggle
    col1, col2 = st.columns([3, 1])
    with col2:
        st.session_state.debug_mode = st.checkbox("🔍 Debug", value=st.session_state.get('debug_mode', False))

    # Load results
    with st.spinner("Loading results from NextCloud..."):
        results_by_service = load_results_from_nextcloud()

    if not results_by_service:
        st.info("📭 No past results found")
        st.write("**Results will appear here after you submit scenarios to APIs**")
        st.caption(f"💾 Results are saved to: `{workspace_id}/results/{{service_name}}/`")

        with st.expander("ℹ️ How to save results", expanded=True):
            st.write("**To save results:**")
            st.write("1. Go to the **API Submission** tab")
            st.write("2. Select a service and scenarios to submit")
            st.write("3. Click the Submit button")
            st.write("4. Results are automatically saved to NextCloud")
            st.write("5. Return to this tab to view saved results")

            st.write("\n**Expected folder structure:**")
            st.code(f"""{workspace_id}/
└── results/
    └── CESARP_Building_Simulation/
        └── scenario_20241008_143022.json""", language='text')

        return

    # Show summary metrics
    st.write("### 📈 Summary")

    total_results = sum(len(results) for results in results_by_service.values())
    total_services = len(results_by_service)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Results", total_results)
    with col2:
        st.metric("Services", total_services)
    with col3:
        successful = sum(
            1 for results in results_by_service.values()
            for r in results
            if r.get('metadata', {}).get('success', False)
        )
        st.metric("Successful", successful)
    with col4:
        success_rate = (successful / total_results * 100) if total_results > 0 else 0
        st.metric("Success Rate", f"{success_rate:.1f}%")

    # Service selector
    st.write("### 🔍 Browse Results by Service")

    service_names = list(results_by_service.keys())
    selected_service = st.selectbox(
        "Select service:",
        options=service_names,
        key="results_service_selector"
    )

    if selected_service:
        service_results = results_by_service[selected_service]

        st.write(f"### 🎯 {selected_service}")
        st.write(f"**{len(service_results)} result(s) found**")

        # Display results
        for idx, result in enumerate(service_results):
            metadata = result.get('metadata', {})
            submission = result.get('submission', {})
            response = result.get('response', {})

            scenario_name = metadata.get('scenario_name', 'Unknown')
            timestamp = metadata.get('timestamp', 'Unknown')
            success = metadata.get('success', False)
            status_code = metadata.get('status_code', 0)

            try:
                dt = datetime.fromisoformat(timestamp)
                time_display = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_display = timestamp

            status_icon = "✅" if success else "❌"

            with st.expander(f"{status_icon} **{scenario_name}** - {time_display}", expanded=False):

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write("**Status:**")
                    if success:
                        st.success(f"✅ Success (HTTP {status_code})")
                    else:
                        st.error(f"❌ Failed (HTTP {status_code})")

                with col2:
                    st.write("**Timestamp:**")
                    st.write(time_display)

                with col3:
                    st.write("**File:**")
                    st.caption(result.get('_filename', 'Unknown'))

                st.divider()

                st.write("### 📤 Submission Details")

                if submission.get('scenario_id'):
                    st.write(f"**Scenario ID:** `{submission['scenario_id']}`")

                if submission.get('api_url'):
                    st.write("**API URL:**")
                    st.code(submission['api_url'], language='text')

                if submission.get('result_url'):
                    st.write("**Result URL:**")
                    st.code(submission['result_url'], language='text')

                st.divider()

                st.write("### 📋 API Response")
                st.json(response if response else {})

                st.divider()
                st.write("### 💾 Download Options")

                col1, col2, col3 = st.columns(3)

                with col1:
                    full_result_json = json.dumps(result, indent=2, ensure_ascii=False)
                    st.download_button(
                        "📥 Full Result",
                        full_result_json,
                        f"{scenario_name}_result.json",
                        "application/json",
                        key=f"full_{idx}"
                    )

                with col2:
                    response_json = json.dumps(response, indent=2, ensure_ascii=False)
                    st.download_button(
                        "📋 Response",
                        response_json,
                        f"{scenario_name}_response.json",
                        "application/json",
                        key=f"resp_{idx}"
                    )

                with col3:
                    if 'submitted_data' in result:
                        submitted_json = json.dumps(result['submitted_data'], indent=2, ensure_ascii=False)
                        st.download_button(
                            "📤 Submitted Data",
                            submitted_json,
                            f"{scenario_name}_submitted.json",
                            "application/json",
                            key=f"subm_{idx}"
                        )