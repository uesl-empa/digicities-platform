# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
API Submission Core Module
File: components/api_submission_module/submission_core.py

Handles actual API submissions and result management for multiple configured services.
Delivers payloads to any configured service through the backend transport layer.
Now includes automatic result saving to NextCloud.
"""

import os
import streamlit as st
import pandas as pd
import json
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from .api_config import ServiceAPI
from .validation import ValidationResult, validate_payload, render_validation


@dataclass
class SubmissionResult:
    """Result of API submission"""
    success: bool
    status_code: int = 0
    response_data: Dict = field(default_factory=dict)
    error_message: str = ""
    submission_time: datetime = field(default_factory=datetime.now)
    # Service-specific fields
    scenario_id: str = ""
    result_url: str = ""
    api_url: str = ""
    service_name: str = ""


def submit_to_api(data: Dict, api_config: ServiceAPI) -> SubmissionResult:
    """Submit a payload to a registered service via its configured transport.

    The payload is delivered through the backend transport layer — HTTP (default)
    or Redis — so Digicities stays decoupled from any particular service stack.
    """
    from backend.api_submission.transports import submit_http, submit_redis

    result = SubmissionResult(success=False, service_name=api_config.service_name)
    result.submission_time = datetime.now()

    transport = (getattr(api_config, "transport", "http") or "http").lower()

    if transport == "redis":
        rc = getattr(api_config, "redis_config", None) or {}
        tr = submit_redis(
            data,
            request_stream=rc.get("request_stream", ""),
            host=rc.get("host", "localhost"),
            port=int(rc.get("port", 6379)),
            result_stream=rc.get("result_stream") or None,
            payload_field=rc.get("payload_field", "payload"),
            request_id_field=rc.get("request_id_field", "request_id"),
            encode_payload_as_json=rc.get("encode_payload_as_json", True),
            poll_timeout=int(rc.get("poll_timeout", api_config.timeout)),
        )
        result.api_url = f"redis://{rc.get('host', 'localhost')}:{rc.get('port', 6379)}/{rc.get('request_stream', '')}"
        result.scenario_id = tr.request_id
    else:
        # Build auth + headers, then deliver over HTTP.
        headers = dict(api_config.headers or {})
        auth = None
        creds = api_config.auth_credentials or {}
        if api_config.auth_type == "bearer" and "token" in creds:
            headers["Authorization"] = f"Bearer {creds['token']}"
        elif api_config.auth_type == "api_key" and "header_name" in creds and "api_key" in creds:
            headers[creds["header_name"]] = creds["api_key"]
        elif api_config.auth_type == "basic" and "username" in creds and "password" in creds:
            auth = (creds["username"], creds["password"])

        tr = submit_http(
            data,
            url=api_config.api_url,
            method=api_config.api_method,
            headers=headers,
            auth=auth,
            timeout=api_config.timeout,
        )
        result.api_url = api_config.api_url

    # Map the transport result onto the SubmissionResult the UI consumes.
    result.success = tr.success
    result.status_code = tr.status_code
    result.response_data = tr.response_data or {}
    result.error_message = tr.error_message
    if isinstance(result.response_data, dict):
        result.scenario_id = result.response_data.get("scenario_id", result.scenario_id)
        result.result_url = result.response_data.get("result_url", "")
    return result


def render_api_submission_tab():
    """Render API submission tab - Enhanced for multiple services"""
    st.subheader("🚀 API Submission")
    st.write("Submit converted data to configured service APIs")

    # Check if there are any configured APIs
    configured_apis = st.session_state.get('registered_apis', {})

    if not configured_apis:
        st.warning("⚠️ No APIs configured. Please configure at least one API in the 'API Configuration' tab.")
        return

    # Show all configured APIs
    st.write("### 🔌 Available APIs")

    # Create a selection interface for APIs
    api_options = []
    api_display_map = {}

    for service_name, api_config in configured_apis.items():
        # Status indicator icon.
        icon = "🟢"
        display_name = f"{icon} {service_name} - {api_config.api_url}"
        api_options.append(display_name)
        api_display_map[display_name] = service_name

    # Let user select which API to use
    selected_api_display = st.selectbox(
        "Select API for submission:",
        options=api_options,
        help="Choose which configured API to submit data to"
    )

    if not selected_api_display:
        st.info("Please select an API to continue")
        return

    selected_service = api_display_map[selected_api_display]
    api_config = configured_apis[selected_service]

    # Display selected API details
    st.write(f"### 🎯 Selected API: **{selected_service}**")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Service", selected_service)
    with col2:
        st.metric("Method", api_config.api_method)
    with col3:
        auth_display = "JWT (from .env)" if api_config.auth_type == "jwt_env" else (api_config.auth_type.title() if api_config.auth_type != "none" else "None")
        st.metric("Auth", auth_display)
    with col4:
        st.metric("Timeout", f"{api_config.timeout}s")

    st.code(api_config.api_url, language='text')

    # Tabs for different submission modes
    tab1, tab2 = st.tabs(["📤 Submit Converted Scenarios", "🧪 Test with Sample Data"])

    with tab1:
        render_converted_scenarios_submission(selected_service, api_config)

    with tab2:
        render_sample_data_test(selected_service, api_config)


def render_converted_scenarios_submission(selected_service: str, api_config: ServiceAPI):
    """Render submission interface for converted scenarios"""

    # Check for converted scenarios
    if 'conversion_results' not in st.session_state or not st.session_state.conversion_results:
        st.info("📁 No converted scenarios available. Please convert TTL files first in the 'Upload & Convert' tab.")
        return

    # Get ready scenarios, restricted to those converted FOR this service, so a
    # scenario built for another service can't be submitted to the wrong one.
    ready_scenarios = {
        name: result for name, result in st.session_state.conversion_results.items()
        if result['success'] and result.get('service') == selected_service
    }

    if not ready_scenarios:
        # Distinguish "converted, but for another service" from "nothing converted".
        converted_other = sorted({
            r.get('service') for r in st.session_state.conversion_results.values()
            if r.get('success') and r.get('service') and r.get('service') != selected_service
        })
        if converted_other:
            st.warning(
                f"🚫 No scenarios converted for **{selected_service}**. "
                f"The converted scenarios are for: {', '.join(converted_other)}. "
                f"Convert scenarios for **{selected_service}** in the 'Upload & Convert' tab.")
        else:
            st.warning("🚫 No successfully converted scenarios available for submission")
        return

    st.write(f"### 📋 Available Scenarios ({len(ready_scenarios)})")

    # Scenario selection with select all option
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("Select scenarios to submit:")
    with col2:
        select_all = st.checkbox("Select All", key="select_all_scenarios")

    selected_scenarios = []

    for scenario_name, result in ready_scenarios.items():
        # Show quality indicators
        stats = result.get('stats', {})
        quality = stats.get('data_quality', 'unknown')
        quality_icon = {'good': '🟢', 'needs_review': '🟡', 'poor': '🔴', 'unknown': '⚪'}.get(quality, '⚪')
        placeholders = stats.get('placeholder_count', 0)
        placeholder_text = f" ⚠️ {placeholders} placeholders" if placeholders > 0 else ""

        is_selected = st.checkbox(
            f"{quality_icon} **{scenario_name}**{placeholder_text}",
            value=select_all,
            key=f"select_{scenario_name}_{selected_service}"
        )

        if is_selected:
            selected_scenarios.append(scenario_name)

    if not selected_scenarios:
        st.info("📁 Select scenarios above to enable submission")
        return

    st.success(f"✅ {len(selected_scenarios)} scenario(s) selected")

    # --- Validate selected scenarios against the service template (P0) ---
    # A green tick must mean "this scenario genuinely has what the service needs".
    st.write("### 🔎 Validation")
    blocking, warned = [], []
    for scenario_name in selected_scenarios:
        vr = ready_scenarios[scenario_name].get('validation')
        if vr is None:
            continue
        icon = "🟢" if (vr.is_valid and not vr.warnings) else ("🔴" if not vr.is_valid else "🟡")
        with st.expander(f"{icon} {scenario_name}", expanded=not vr.is_valid):
            render_validation(vr)
        if not vr.is_valid:
            blocking.append(scenario_name)
        elif vr.warnings:
            warned.append(scenario_name)

    submittable = [s for s in selected_scenarios if s not in blocking]

    if blocking:
        st.error(
            f"🔴 {len(blocking)} scenario(s) fail validation and will be skipped: "
            + ", ".join(blocking)
        )

    # Submission options - minimal and clean
    st.write("### ⚙️ Submission Options")

    detailed_logging = st.checkbox("📝 Detailed logging", value=True, help="Show detailed progress for each scenario")

    if not submittable:
        st.warning("🚫 No selected scenarios pass validation. Fix the inputs above before submitting.")
        return

    # Require an explicit acknowledgement when something didn't resolve.
    confirm = True
    warned_submittable = [s for s in warned if s in submittable]
    if warned_submittable:
        confirm = st.checkbox(
            f"⚠️ {len(warned_submittable)} scenario(s) have missing or unresolved attributes. "
            f"Submit anyway? The service may fill defaults, which can give a meaningless result.",
            key=f"confirm_submit_{selected_service}"
        )

    # Submit button
    button_text = f"🚀 Submit {len(submittable)} Scenario(s) to {selected_service}"

    if st.button(button_text, type="primary", use_container_width=True, disabled=not confirm):
        # Call with correct parameters
        execute_submission(
            selected_scenarios=submittable,
            selected_service=selected_service,
            api_config=api_config,
            detailed_logging=detailed_logging
        )


def render_sample_data_test(selected_service: str, api_config: ServiceAPI):
    """Render sample data test interface"""

    st.write("### 🧪 Test API with Sample Data")
    st.info(f"Test the **{selected_service}** API with pre-configured sample data")

    # Generate appropriate sample data based on service
    if "CESARP" in selected_service or "Energy" in selected_service.lower():
        sample_data = {
            "service_name": selected_service,
            "scenario_data": {
                "uri": "https://digicities.info/proj/sample/test_scenario",
                "name": "Test_Scenario",
                "location": {
                    "uri": "https://digicities.info/dataproducts/test/Location/TestCity",
                    "weather_data": "test_weather.epw",
                    "buildings": [
                        {
                            "uri": "https://digicities.info/dataproducts/test/Building/test1",
                            "SIA2024BuildingType": "MFH",
                            "BuildingAge": "01-01-1990",
                            "GroundFloorArea": 500.0,
                            "NumberOfFloors": 3.0,
                            "HeatingSupply": "GasHeated",
                            "DHWSupply": "GasHeated"
                        }
                    ]
                }
            }
        }
    else:
        # Generic sample data for other services
        sample_data = {
            "service_name": selected_service,
            "scenario_data": {
                "uri": "https://example.com/test_scenario",
                "name": "Test_Scenario",
                "data": {
                    "test_field1": "value1",
                    "test_field2": 123,
                    "test_field3": ["item1", "item2"]
                }
            }
        }

    # Show and allow editing of sample data
    st.write("**Sample Data:**")
    sample_json = st.text_area(
        "Edit sample data (JSON format):",
        value=json.dumps(sample_data, indent=2),
        height=300,
        key=f"sample_data_{selected_service}"
    )

    # Parse edited JSON
    try:
        sample_data = json.loads(sample_json)
        st.success("✅ Valid JSON")
    except json.JSONDecodeError as e:
        st.error(f"❌ Invalid JSON: {str(e)}")
        return

    # Download button for sample
    st.download_button(
        "📥 Download Sample JSON",
        sample_json,
        f"sample_{selected_service}.json",
        "application/json",
        key=f"download_sample_{selected_service}"
    )

    # Test submission button
    if st.button(f"🚀 Test {selected_service} API", type="primary", use_container_width=True):
        with st.spinner(f"Testing {selected_service} API..."):
            try:
                # Submit to API
                result = submit_to_api(sample_data, api_config)

                if result.success:
                    st.success(f"✅ **Test successful for {selected_service}!**")
                    st.balloons()

                    # Show results
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Status Code", result.status_code)

                    with col2:
                        if result.scenario_id:
                            st.metric("Scenario ID", result.scenario_id[:20] + "..." if len(result.scenario_id) > 20 else result.scenario_id)

                    if result.result_url:
                        st.write("**Result URL:**")
                        st.code(result.result_url, language='text')

                    # Show response
                    with st.expander("📋 Full API Response", expanded=False):
                        st.json(result.response_data)

                    st.success(f"🎉 {selected_service} API is working correctly!")

                else:
                    st.error(f"❌ **Test failed for {selected_service}**")
                    st.error(f"Error: {result.error_message}")

                    # Troubleshooting tips
                    if "Connection error" in result.error_message:
                        st.warning("💡 **Troubleshooting Tips:**")
                        st.write(f"1. Check that your server is running at: {api_config.api_url}")
                        st.write("2. Verify the API endpoint is correct")
                        st.write("3. Check firewall/network settings")

                    if result.response_data:
                        with st.expander("📋 Response Details", expanded=True):
                            st.json(result.response_data)

            except Exception as e:
                st.error(f"❌ Unexpected error: {str(e)}")
                st.write("Please check your API configuration.")


def execute_submission(
    selected_scenarios: List[str],
    selected_service: str,
    api_config: ServiceAPI,
    detailed_logging: bool = True
):
    """Execute the actual submission process - clean and simple"""

    st.write("### 🚀 Submission Process")

    st.info(f"📡 **Submitting to {selected_service}**")

    # Initialize submission tracking
    submission_results = {}
    service_results = []
    start_time = datetime.now()

    # Progress tracking
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, scenario_name in enumerate(selected_scenarios):
        progress = (i + 1) / len(selected_scenarios)
        progress_bar.progress(progress)

        # Status indicator
        status_text.text(f"Processing {scenario_name} ({i + 1}/{len(selected_scenarios)})")

        if detailed_logging:
            st.write(f"**Processing:** {scenario_name} → {selected_service}")

        try:
            # Get converted data
            if scenario_name not in st.session_state.conversion_results:
                raise Exception(f"No conversion data found for {scenario_name}")

            conversion = st.session_state.conversion_results[scenario_name]

            # Safety net: never submit a payload that failed validation.
            validation = conversion.get('validation')
            if validation is not None and not validation.is_valid:
                raise Exception(
                    "Failed validation: " + "; ".join(validation.errors)
                )

            original_data = conversion['data']

            # Ensure service name matches
            if 'service_name' in original_data:
                original_data['service_name'] = selected_service

            # Actual submission (no dry run)
            result = submit_to_api(original_data, api_config)

            submission_results[scenario_name] = result

            # Pull the full result from the service (via the internal endpoint
            # the app already uses) so the copy saved to the workspace is
            # complete — not just the submission summary. Best-effort.
            try:
                if (result.success and result.scenario_id and api_config.api_url
                        and api_config.transport == "http"):
                    detail_url = api_config.api_url.rstrip('/') + f"/results/{result.scenario_id}"
                    dr = requests.get(detail_url, timeout=15)
                    if dr.status_code == 200:
                        result.response_data = {**(result.response_data or {}),
                                                "result_detail": dr.json()}
            except Exception:
                pass

            # Persist the result to the workspace storage (the workspace's
            # NextCloud when it is NextCloud-backed; local files otherwise).
            try:
                from .results_viewer import save_submission_result_to_nextcloud
                saved = save_submission_result_to_nextcloud(
                    service_name=selected_service,
                    scenario_name=scenario_name,
                    submission_result=result,
                    submitted_data=original_data
                )
                if saved and detailed_logging:
                    st.caption("💾 Result saved to the workspace")
            except Exception as save_error:
                if st.session_state.get('debug_mode'):
                    st.warning(f"⚠️ Could not save to NextCloud: {str(save_error)}")

            # Store in history
            if 'submission_history' not in st.session_state:
                st.session_state.submission_history = []

            submission_record = {
                'scenario': scenario_name,
                'service': selected_service,
                'timestamp': result.submission_time,
                'success': result.success,
                'status_code': result.status_code,
                'dry_run': False,
                'scenario_id': result.scenario_id,
                'result_url': result.result_url,
                'api_url': api_config.api_url
            }

            st.session_state.submission_history.append(submission_record)

            # Store service-specific results
            if result.success and result.scenario_id:
                service_result = {
                    'scenario_name': scenario_name,
                    'service_name': selected_service,
                    'scenario_id': result.scenario_id,
                    'result_url': result.result_url,
                    'api_url': api_config.api_url,
                    'response_data': result.response_data,
                    'timestamp': result.submission_time
                }

                service_results.append(service_result)

            # Show result with appropriate icon
            if detailed_logging:
                if result.success:
                    status_icon = "✅"
                    st.success(f"{status_icon} {scenario_name} → {selected_service} successful!")

                    # Links for whatever URLs the service returned.
                    _render_response_links(result.response_data)
                    if not isinstance(result.response_data, dict) and result.result_url:
                        st.write(f"🔗 Result: {result.result_url}")
                else:
                    st.error(f"❌ {scenario_name} failed: {result.error_message}")

        except Exception as e:
            error_result = SubmissionResult(
                success=False,
                error_message=str(e),
                submission_time=datetime.now(),
                service_name=selected_service
            )
            submission_results[scenario_name] = error_result

            if detailed_logging:
                st.error(f"❌ {scenario_name} failed: {str(e)}")

    # Clear progress indicators
    progress_bar.empty()
    status_text.empty()

    # Store service results
    if service_results:
        if 'service_submission_results' not in st.session_state:
            st.session_state.service_submission_results = {}
        if selected_service not in st.session_state.service_submission_results:
            st.session_state.service_submission_results[selected_service] = []
        st.session_state.service_submission_results[selected_service].extend(service_results)

    # Show summary - always show responses
    show_submission_summary(submission_results, selected_service, start_time, dry_run=False, show_responses=True)


def _render_response_links(response_data):
    """Render clickable links for whatever URL fields a service returned.

    Services differ - one returns a dashboard, another a JSON download, another a
    results API - so we don't hardcode: any field whose name ends in 'url' (top
    level or inside a `processed` list) is shown as a link, with a friendly label.
    """
    if not isinstance(response_data, dict):
        return

    labels = {
        "result_url": "📊 Open dashboard",
        "dashboard_url": "📊 Open dashboard",
        "download_url": "💾 Download results (JSON)",
        "results_api_url": "🔗 Results (JSON API)",
        "api_url": "🔗 Results (JSON API)",
        "execution_url": "📁 Execution files",
        "scenario_url": "📊 Scenario view",
    }

    def is_url(v):
        return isinstance(v, str) and v.startswith(("http://", "https://"))

    def label_for(key):
        return labels.get(key, "🔗 " + key.replace("_url", "").replace("_", " ").strip().title())

    seen, links = set(), []

    def collect(d, suffix=""):
        for k, v in d.items():
            if isinstance(k, str) and k.lower().endswith("url") and is_url(v) and v not in seen:
                seen.add(v)
                links.append((label_for(k) + suffix, v))

    collect(response_data)
    for item in (response_data.get("processed") or []):
        if isinstance(item, dict):
            bid = item.get("id") or item.get("uri")
            suffix = f" (building {str(bid).rsplit('/', 1)[-1]})" if bid else ""
            collect(item, suffix)

    if links:
        st.write("**🔗 Links**")
        for lbl, url in links:
            st.markdown(f"- [{lbl}]({url})")


def show_submission_summary(submission_results: Dict, selected_service: str, start_time: datetime,
                           dry_run: bool, show_responses: bool):
    """Show summary of submission results"""

    total_time = datetime.now() - start_time
    st.write(f"### 📊 {'Simulation' if dry_run else 'Submission'} Results for {selected_service}")

    successful = sum(1 for result in submission_results.values() if result.success)
    total = len(submission_results)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total", total)
    with col2:
        st.metric("Successful", successful)
    with col3:
        success_rate = (successful / total * 100) if total > 0 else 0
        st.metric("Success Rate", f"{success_rate:.1f}%")
    with col4:
        st.metric("Time", f"{total_time.total_seconds():.1f}s")

    # Detailed results
    if show_responses:
        st.write("### 📋 Detailed Results")
        for scenario_name, result in submission_results.items():
            status_icon = "✅" if result.success else "❌"

            with st.expander(f"{status_icon} **{scenario_name}**", expanded=not result.success):
                if result.success:
                    st.success(f"✅ Successfully submitted to {selected_service}")

                    status_line = f"**Status Code:** {result.status_code}"
                    if result.scenario_id:
                        status_line += f"  ·  **Scenario ID:** {result.scenario_id}"
                    st.write(status_line)

                    # Clickable links for whatever URLs the service returned
                    # (dashboard, download, JSON API, ...). Falls back to
                    # result.result_url if the body carried nothing URL-shaped.
                    _render_response_links(result.response_data)
                    if not isinstance(result.response_data, dict) and result.result_url:
                        st.markdown(f"[🔗 View Results]({result.result_url})")

                    # Show response data
                    if result.response_data:
                        st.write("**Response Data:**")
                        st.json(result.response_data)
                else:
                    st.error(f"❌ Submission failed")
                    st.write(f"**Error:** {result.error_message}")
                    if result.response_data:
                        st.json(result.response_data)


def render_footer():
    """Render footer with current status"""
    st.markdown("---")

    # Get counts
    configured_apis = len(st.session_state.get('registered_apis', {}))
    conversion_results = len(st.session_state.get('conversion_results', {}))
    total_submissions = len(st.session_state.get('submission_history', []))
    successful_submissions = len([s for s in st.session_state.get('submission_history', []) if s['success']])

    # Count submissions by service
    service_counts = {}
    for submission in st.session_state.get('submission_history', []):
        service = submission.get('service', 'Unknown')
        service_counts[service] = service_counts.get(service, 0) + 1

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("APIs Configured", configured_apis)
    with col2:
        st.metric("Conversions", conversion_results)
    with col3:
        st.metric("Total Submissions", total_submissions)
    with col4:
        st.metric("Successful", successful_submissions)
    with col5:
        st.metric("Services Used", len(service_counts))

    # Service-specific results dashboard
    if st.session_state.get('service_submission_results'):
        with st.expander("📊 Submission Results by Service", expanded=False):
            for service_name, results in st.session_state.service_submission_results.items():
                st.write(f"### {service_name} ({len(results)} submissions)")

                if results:
                    # Show recent submissions for this service
                    recent_results = sorted(results, key=lambda x: x['timestamp'], reverse=True)[:5]
                    for result in recent_results:
                        st.write(f"• **{result['scenario_name']}** - {result['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                        if result.get('result_url'):
                            st.write(f"  [🔗 View Results]({result['result_url']})")

            if st.button("🗑️ Clear All Results"):
                st.session_state.service_submission_results = {}
                st.session_state.submission_history = []
                st.rerun()

    # Submission history by service
    if service_counts:
        with st.expander("📈 Submission Statistics", expanded=False):
            st.write("**Submissions by Service:**")

            # Create a simple bar chart representation
            for service, count in sorted(service_counts.items(), key=lambda x: x[1], reverse=True):
                success_count = len([s for s in st.session_state.submission_history
                                   if s.get('service') == service and s.get('success')])
                success_rate = (success_count / count * 100) if count > 0 else 0

                st.write(f"**{service}**")
                st.progress(success_count / count if count > 0 else 0)
                st.caption(f"{success_count}/{count} successful ({success_rate:.1f}%)")