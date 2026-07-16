# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
API Configuration Module
File: components/api_submission_module/api_config.py

Handles API configuration and service template management.
Self-contained to avoid circular imports.

Layout is intentionally minimal: the essentials (one-click connect for bundled
demos + the list of registered services) are always visible; the full connection
form only appears when you open "Add or edit a service connection".
"""

import streamlit as st
import json
import yaml
import os
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path


# Export key functions and classes to avoid import errors
__all__ = ['ServiceAPI', 'load_service_requirements', 'get_service_template_content', 'render_api_configuration_tab']


@dataclass
class ServiceAPI:
    """Registered service: where it listens and how to reach it.

    ``transport`` selects how the payload is delivered:
    - ``"http"``  (default): POST/PUT the JSON payload to ``api_url`` (with auth).
    - ``"redis"``: publish the payload to a Redis request stream and optionally
      poll a result stream — see ``redis_config`` (keys: host, port,
      request_stream, result_stream, payload_field, request_id_field,
      encode_payload_as_json, poll_timeout).

    Nothing here is specific to any stack: a service is described purely by its
    transport + connection details. The payload *shape* comes from the service's
    requirements template, not from this object.
    """
    service_name: str
    api_url: str = ""
    api_method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    auth_type: str = "none"  # none, bearer, api_key, basic
    auth_credentials: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    description: str = ""
    transport: str = "http"  # "http" | "redis"
    redis_config: Dict[str, Any] = field(default_factory=dict)


def load_service_requirements() -> Dict[str, Dict]:
    """Load service requirements from NextCloud global/services/ with local fallback."""
    services = {}

    # Discover services from the global library + the active workspace's
    # services/ folder through the shared catalog (one implementation across the
    # platform). Global first so a global service wins a name collision.
    try:
        from components.service_catalog import list_global_services, list_workspace_services

        discovered = 0
        for ref in list_global_services() + list_workspace_services():
            if ref.content is None or ref.name in services:
                continue
            services[ref.name] = {
                'file_path': ref.ref,
                'filename': ref.filename,
                'requirements': ref.content,
                'name': ref.name,
                'template': ref.content,
                'source': 'nextcloud_global' if ref.source == 'global' else 'workspace',
                'description': ref.content.get('description', f'{ref.source.title()} service: {ref.filename}'),
            }
            discovered += 1
    except Exception as e:
        if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
            if st.session_state.get('debug_mode'):
                st.warning(f"⚠️ Could not discover services: {e}")

    return services


def get_service_template_content(service_info: Dict) -> Dict:
    """Get the template content from service info (NextCloud or local)."""

    # Check if this is a NextCloud service that needs to be reloaded
    if service_info.get('source') == 'nextcloud_global':
        try:
            from components.nextcloud_global_client import get_global_nextcloud_client

            global_client = get_global_nextcloud_client()
            if global_client:
                filename = service_info.get('filename')
                if filename:
                    service_content = global_client.get_service_file_content(filename)
                    if service_content:
                        return yaml.safe_load(service_content)
        except:
            # Fall back to cached template
            pass

    # If template is directly in service_info, return it
    if 'template' in service_info:
        return service_info['template']

    # For local services, try to load from path
    if service_info.get('source') == 'local' and 'template_path' in service_info:
        try:
            with open(service_info['template_path'], 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            if hasattr(st, '_is_running_with_streamlit') and st._is_running_with_streamlit:
                st.error(f"Could not load template from {service_info['template_path']}: {e}")
            return None

    # Return requirements if available
    if 'requirements' in service_info:
        return service_info['requirements']

    return None


# --------------------------------------------------------------------------- #
# Bundled demo services — one-click connect
# --------------------------------------------------------------------------- #

import re


def _expand_env(value: Any) -> Any:
    """Expand ${VAR} / ${VAR:-default} against the environment (compose-style).

    Lets a template's connection block reference deployment-specific values, e.g.
    url: ${FLEX_ADAPTER_URL:-http://host.docker.internal:8090/run}
    """
    if not isinstance(value, str):
        return value

    def repl(m):
        var, default = m.group(1), m.group(3)
        return os.environ.get(var, default if default is not None else "")

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}", repl, value)


def service_api_from_connection(service_name: str, conn: Dict, description: str = "") -> ServiceAPI:
    """Build a ServiceAPI from a service template's optional ``connection:`` block.

    The block declares where the service listens (transport + connection details),
    so selecting/registering it needs no manual typing. Example (HTTP)::

        connection:
          transport: http
          url: ${FLEX_ADAPTER_URL:-http://host.docker.internal:8090/run}
          method: POST
          auth_type: none
          timeout: 180

    or (Redis)::

        connection:
          transport: redis
          host: host.docker.internal
          port: 6379
          request_stream: flexibility.requests
          result_stream: flexibility.results
    """
    conn = conn or {}
    transport = str(conn.get("transport", "http")).lower()
    if transport == "redis":
        redis_cfg = {
            "host": _expand_env(conn.get("host", "localhost")),
            "port": int(conn.get("port", 6379)),
            "request_stream": _expand_env(conn.get("request_stream", "")),
            "result_stream": _expand_env(conn.get("result_stream", "")),
            "payload_field": conn.get("payload_field", "payload"),
            "request_id_field": conn.get("request_id_field", "request_id"),
            "encode_payload_as_json": bool(conn.get("encode_payload_as_json", True)),
            "poll_timeout": int(conn.get("poll_timeout", conn.get("timeout", 120))),
        }
        return ServiceAPI(service_name=service_name, transport="redis",
                          timeout=int(conn.get("timeout", redis_cfg["poll_timeout"])),
                          description=description, redis_config=redis_cfg)
    return ServiceAPI(
        service_name=service_name, transport="http",
        api_url=_expand_env(conn.get("url", "")),
        api_method=str(conn.get("method", "POST")).upper(),
        headers=conn.get("headers", {}) or {},
        auth_type=str(conn.get("auth_type", "none")),
        auth_credentials=conn.get("auth_credentials", {}) or {},
        timeout=int(conn.get("timeout", 60)),
        description=description,
    )


def _autoregister_from_templates(services: Dict[str, Dict]) -> int:
    """Register every service whose template declares a ``connection:`` block.

    Runs on tab load, so opening a workspace wires up its services automatically -
    no manual API configuration. A service the user removed this session is
    suppressed so it doesn't come back; the connection form can still edit any of
    them (their fields are pre-filled from the registration above).
    """
    if "registered_apis" not in st.session_state:
        st.session_state.registered_apis = {}
    suppressed = st.session_state.setdefault("suppressed_services", set())
    n = 0
    for name, info in services.items():
        conn = (info.get("template") or {}).get("connection")
        if not conn or name in st.session_state.registered_apis or name in suppressed:
            continue
        try:
            st.session_state.registered_apis[name] = service_api_from_connection(
                name, conn, info.get("description", ""))
            n += 1
        except Exception as e:
            if st.session_state.get("debug_mode"):
                st.warning(f"Could not auto-register '{name}' from its template: {e}")
    return n


def _render_registered_services() -> None:
    """Compact list of registered services with a per-service remove button."""
    apis = st.session_state.registered_apis
    if not apis:
        st.info("No services connected yet. Add one below, or give a service template a "
                "`connection:` block and it will connect automatically.")
        return

    st.markdown("**Registered services**")
    for name, api in list(apis.items()):
        c1, c2, c3 = st.columns([3, 4, 1])
        with c1:
            st.write(f"**{name}**")
        with c2:
            if getattr(api, "transport", "http") == "redis":
                rc = api.redis_config or {}
                st.caption(f"redis · `{rc.get('host')}:{rc.get('port')}` · {rc.get('request_stream')}")
            else:
                auth = f" · 🔒 {api.auth_type}" if api.auth_type not in ("none", "") else ""
                st.caption(f"`{api.api_method} {api.api_url}`{auth}")
        with c3:
            if st.button("Remove", key=f"rm_{name}", use_container_width=True):
                del st.session_state.registered_apis[name]
                # Suppress re-adding by the template auto-register on the next run.
                st.session_state.setdefault("suppressed_services", set()).add(name)
                st.rerun()


def _render_connection_editor(services: Dict[str, Dict]) -> None:
    """Full connection form: pick a service template, choose a transport, fill in
    the connection details. Only rendered inside the collapsed expander, so these
    parameters stay out of the way until you actually add/edit a service."""

    service_options = sorted(services.keys())
    selected_service = st.selectbox(
        "Service template",
        options=service_options,
        help="Templates come from the workspace `services/` folder and the global library.",
    )
    if not selected_service:
        return

    service_info = services[selected_service]
    source = service_info.get('source', 'unknown')
    source_text = {'nextcloud_global': '☁️ Global library', 'workspace': '📁 Workspace'}.get(source, source)
    st.caption(f"Source: {source_text}")

    existing_api = st.session_state.registered_apis.get(selected_service)
    existing_redis = getattr(existing_api, "redis_config", {}) if existing_api else {}

    # Transport selection lives OUTSIDE the form so the relevant fields appear
    # without needing a submit first (st.form widgets don't rerun until submit).
    transport_options = ["http", "redis"]
    default_transport = getattr(existing_api, "transport", "http") if existing_api else "http"
    transport = st.radio(
        "Transport",
        transport_options,
        index=transport_options.index(default_transport) if default_transport in transport_options else 0,
        horizontal=True,
        key=f"transport_{selected_service}",
        help=("http: POST/PUT the payload to an endpoint. "
              "redis: publish the payload to a Redis stream (and optionally poll a result stream)."),
    )

    with st.form(f"api_config_{selected_service}"):
        # Defaults for fields not shown by the active transport.
        api_url, api_method, auth_type, auth_credentials, headers_json = "", "POST", "none", {}, "{}"
        redis_cfg = {}

        if transport == "http":
            col1, col2 = st.columns(2)
            with col1:
                api_url = st.text_input(
                    "API URL",
                    value=existing_api.api_url if existing_api else "",
                    placeholder="http://localhost:8000/run",
                    help="Full URL of the service endpoint",
                )
                api_method = st.selectbox(
                    "HTTP Method", options=["POST", "PUT"],
                    index=(["POST", "PUT"].index(existing_api.api_method)
                           if existing_api and existing_api.api_method in ("POST", "PUT") else 0),
                )
            with col2:
                timeout = st.number_input(
                    "Timeout (seconds)", min_value=5, max_value=600,
                    value=existing_api.timeout if existing_api else 60,
                )
                auth_type = st.selectbox(
                    "Authentication", options=["none", "bearer", "api_key", "basic"],
                    index=(["none", "bearer", "api_key", "basic"].index(existing_api.auth_type)
                           if existing_api and existing_api.auth_type in ("none", "bearer", "api_key", "basic") else 0),
                )

            auth_credentials = {}
            if auth_type == "bearer":
                token = st.text_input("Bearer Token", type="password",
                                      value=existing_api.auth_credentials.get("token", "") if existing_api else "")
                if token:
                    auth_credentials["token"] = token
            elif auth_type == "api_key":
                c1, c2 = st.columns(2)
                with c1:
                    header_name = st.text_input("Header Name",
                        value=existing_api.auth_credentials.get("header_name", "X-API-Key") if existing_api else "X-API-Key")
                with c2:
                    api_key = st.text_input("API Key", type="password",
                        value=existing_api.auth_credentials.get("api_key", "") if existing_api else "")
                if header_name and api_key:
                    auth_credentials["header_name"] = header_name
                    auth_credentials["api_key"] = api_key
            elif auth_type == "basic":
                c1, c2 = st.columns(2)
                with c1:
                    username = st.text_input("Username",
                        value=existing_api.auth_credentials.get("username", "") if existing_api else "")
                with c2:
                    password = st.text_input("Password", type="password",
                        value=existing_api.auth_credentials.get("password", "") if existing_api else "")
                if username and password:
                    auth_credentials["username"] = username
                    auth_credentials["password"] = password

            with st.expander("Additional headers (optional)", expanded=False):
                headers_json = st.text_area(
                    "Headers (JSON)",
                    value=json.dumps(existing_api.headers, indent=2) if existing_api and existing_api.headers else "{}",
                    help='Example: {"Accept": "application/json"}',
                )
        else:  # redis transport
            st.caption("Digicities publishes the payload to a request stream; if a result stream is "
                       "given it polls for the matching request_id.")
            c1, c2 = st.columns(2)
            with c1:
                redis_host = st.text_input("Redis host", value=existing_redis.get("host", "localhost"))
                request_stream = st.text_input("Request stream", value=existing_redis.get("request_stream", ""),
                                               placeholder="empa.flex.requests")
                payload_field = st.text_input("Payload field", value=existing_redis.get("payload_field", "payload"),
                                              help="Message field the payload is placed under")
            with c2:
                redis_port = st.number_input("Redis port", min_value=1, max_value=65535,
                                             value=int(existing_redis.get("port", 6379)))
                result_stream = st.text_input("Result stream (optional)", value=existing_redis.get("result_stream", ""),
                                              placeholder="empa.flex.results",
                                              help="If set, Digicities polls this stream for your request_id")
                request_id_field = st.text_input("Request-id field", value=existing_redis.get("request_id_field", "request_id"))
            encode_payload_as_json = st.checkbox(
                "Encode payload as a JSON string in the payload field",
                value=existing_redis.get("encode_payload_as_json", True),
            )
            timeout = st.number_input("Result poll timeout (seconds)", min_value=5, max_value=600,
                                      value=existing_api.timeout if existing_api else 120)
            redis_cfg = {
                "host": redis_host, "port": int(redis_port), "request_stream": request_stream,
                "result_stream": result_stream, "payload_field": payload_field,
                "request_id_field": request_id_field, "encode_payload_as_json": encode_payload_as_json,
                "poll_timeout": int(timeout),
            }

        description = st.text_area(
            "Description",
            value=existing_api.description if existing_api else service_info.get('description', ''),
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            save_btn = st.form_submit_button("💾 Save", type="primary", use_container_width=True)
        with col2:
            test_btn = st.form_submit_button("🧪 Test", use_container_width=True)
        with col3:
            remove_btn = st.form_submit_button("🗑️ Remove", type="secondary", use_container_width=True)

        if save_btn:
            try:
                headers = json.loads(headers_json) if headers_json.strip() else {}
                st.session_state.registered_apis[selected_service] = ServiceAPI(
                    service_name=selected_service,
                    api_url=api_url,
                    api_method=api_method,
                    headers=headers,
                    auth_type=auth_type,
                    auth_credentials=auth_credentials,
                    timeout=int(timeout),
                    description=description,
                    transport=transport,
                    redis_config=redis_cfg,
                )
                st.success(f"✅ Saved **{selected_service}** ({transport} transport)")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON in headers field")
            except Exception as e:
                st.error(f"❌ Error saving configuration: {str(e)}")

        if test_btn:
            _test_connection(transport, api_url, api_method, auth_type, auth_credentials, headers_json, redis_cfg)

        if remove_btn:
            if selected_service in st.session_state.registered_apis:
                del st.session_state.registered_apis[selected_service]
                st.session_state.setdefault("suppressed_services", set()).add(selected_service)
                st.success(f"✅ Removed {selected_service}")
                st.rerun()
            else:
                st.warning("No configuration to remove")


def _test_connection(transport, api_url, api_method, auth_type, auth_credentials, headers_json, redis_cfg) -> None:
    """Reachability probe for the Save/Test form (HTTP endpoint or Redis server)."""
    if transport == "redis":
        with st.spinner("Testing Redis connection..."):
            try:
                import redis as _redis
                client = _redis.Redis(host=redis_cfg.get("host", "localhost"),
                                      port=int(redis_cfg.get("port", 6379)),
                                      socket_connect_timeout=5)
                client.ping()
                st.success(f"✅ Connected to Redis at {redis_cfg.get('host')}:{redis_cfg.get('port')}")
            except ImportError:
                st.error("❌ The 'redis' package is not installed in this environment.")
            except Exception as e:
                st.error(f"❌ Could not reach Redis: {e}")
        return

    if not api_url:
        st.error("❌ Please provide an API URL")
        return
    with st.spinner("Testing connection..."):
        import requests
        try:
            headers = json.loads(headers_json) if headers_json.strip() else {}
            if auth_type == "bearer" and "token" in auth_credentials:
                headers['Authorization'] = f"Bearer {auth_credentials['token']}"
            elif auth_type == "api_key" and auth_credentials:
                headers[auth_credentials.get("header_name", "X-API-Key")] = auth_credentials.get("api_key", "")
            # Probe with an empty body; <500 means the endpoint is reachable.
            response = requests.request(api_method, api_url, json={}, headers=headers, timeout=5)
            if response.status_code < 500:
                st.success(f"✅ Connection successful! Status: {response.status_code}")
            else:
                st.warning(f"⚠️ Server error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            st.error("❌ Connection failed - could not reach the server")
        except requests.exceptions.Timeout:
            st.error("❌ Connection timeout")
        except Exception as e:
            st.error(f"❌ Test failed: {str(e)}")


def render_api_configuration_tab():
    """Render the streamlined API configuration tab."""
    st.subheader("🔧 API Configuration")
    st.caption("Connect a service, then convert and submit scenarios to it in the other tabs.")

    if 'registered_apis' not in st.session_state:
        st.session_state.registered_apis = {}

    services = load_service_requirements()
    if not services:
        st.info("No service templates found. Add a service YAML to the workspace `services/` folder "
                "(or the global `services/` library), then reopen this tab.")
        return

    # Auto-connect any service whose template declares a connection: block, then
    # show what's connected. Selecting a workspace wires up its services with no
    # manual configuration.
    n = _autoregister_from_templates(services)
    if n:
        st.caption(f"Connected {n} service(s) automatically from their templates.")
    _render_registered_services()

    # Full connection form is tucked away — its parameters only appear when you
    # open this to add or edit a service. Expanded by default only when nothing
    # is connected yet, so a first-time user still sees how to add one.
    with st.expander("➕ Add or edit a service connection",
                     expanded=not st.session_state.registered_apis):
        _render_connection_editor(services)
