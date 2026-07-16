# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""System Status — read-only overview of the local platform.

Surfaces every data connection, storage location, and optional service in a
single sidebar expander so users can answer "where does my data live?" and
"what's configured?" without poking at env vars or the filesystem.

Design rules:
    - Read-only. No buttons that mutate state, no credential editing.
    - Never print credential values. For optional services, show only a
      configured/not-configured indicator.
    - Each check runs in its own try/except — one failure can't blank the page.
    - Sidebar-friendly: compact markdown, no wide columns, ``st.tabs`` instead
      of nested expanders (which Streamlit disallows inside another expander).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #


MAX_FILES_PER_TAB = 50
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — skip huge files in the browser


def _bool_badge(configured: bool, yes: str = "configured", no: str = "not configured") -> str:
    return f"✅ {yes}" if configured else f"⚪ {no}"


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name, default)
    return val if val not in (None, "") else None


def _derive_workbench_url(base_url: Optional[str]) -> str:
    """Pick a URL that a browser on the host can actually open.

    Inside the compose network the client talks to ``http://graphdb:7200``,
    which isn't reachable from the user's browser. Prefer an explicit
    ``GRAPHDB_PUBLIC_URL`` env; otherwise fall back to the port the compose
    file exposes (7201).
    """
    public = _env("GRAPHDB_PUBLIC_URL")
    if public:
        return public.rstrip("/") + "/"
    if base_url and "graphdb:7200" in base_url:
        return "http://localhost:7201/"
    if base_url:
        return base_url.rstrip("/") + "/"
    return "http://localhost:7201/"


def _derive_nextcloud_browser_url(base_url: Optional[str]) -> Optional[str]:
    """Same trick as the GraphDB workbench: the compose-internal URL
    ``http://nextcloud:80`` isn't reachable from the browser. Map it to the
    exposed host port (8080).
    """
    if not base_url:
        return None
    public = _env("NEXTCLOUD_PUBLIC_URL")
    if public:
        return public.rstrip("/") + "/"
    if "nextcloud:80" in base_url:
        return "http://localhost:8080/"
    return base_url.rstrip("/") + "/"


def _human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _dir_totals(path: Path) -> Tuple[int, int]:
    """(file_count, total_bytes) under ``path``. Safe on missing dirs."""
    if not path.exists():
        return (0, 0)
    files = 0
    size = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass
    return files, size


def _list_files(path: Path, limit: int = MAX_FILES_PER_TAB) -> Tuple[List[Path], int]:
    """Return up to ``limit`` files under ``path`` plus the total count."""
    if not path.exists():
        return [], 0
    all_files = [p for p in sorted(path.rglob("*")) if p.is_file()]
    return all_files[:limit], len(all_files)


def _repo_root() -> Path:
    # apps/streamlit/components/system_status.py → repo root is three levels up
    return Path(__file__).resolve().parents[3]


def _kv(key: str, value: str) -> None:
    st.markdown(f"**{key}:** {value}")


# --------------------------------------------------------------------------- #
# Section renderers                                                           #
# --------------------------------------------------------------------------- #


def _section_platform() -> None:
    st.markdown("##### 🧭 Platform")
    env_mode = _env("ENVIRONMENT") or _env("STREAMLIT_ENV") or "(unset)"
    auth_disabled = os.environ.get("AUTH_DISABLED", "false").lower() == "true"
    auth_mode = "disabled (local dev)" if auth_disabled else "Keycloak"
    workspace = st.session_state.get("current_workspace") or _env("LOCAL_WORKSPACE") or "(none)"
    in_container = Path("/.dockerenv").exists()

    _kv("Environment", env_mode)
    _kv("Auth mode", auth_mode)
    _kv("Active workspace", str(workspace))
    _kv("Running in container", "yes" if in_container else "no")


def _section_graphdb(client) -> None:
    st.markdown("##### 🔌 Triplestore")

    base_url = getattr(client, "base_url", None) or _env("GRAPHDB_URL") or "(unset)"
    repository = getattr(client, "repository", None) or _env("GRAPHDB_REPOSITORY") or "(unset)"
    workbench = _derive_workbench_url(base_url)

    _kv("Backend URL", base_url)
    _kv("Current repository", repository)
    _kv("Workbench", f"[{workbench}]({workbench})")

    try:
        ok = bool(client and client.test_connection())
    except Exception as e:  # noqa: BLE001
        ok = False
        st.warning(f"Connection check raised: {e}")

    if not ok:
        st.error("Could not reach Triplestore.")
        return

    st.success("Connected")

    # Named graphs in the current repo — inline table, no nested expander.
    st.caption(f"Named graphs in `{repository}`")
    try:
        df = client.sparql_api_query(
            """
            SELECT ?g (COUNT(*) AS ?triples) WHERE {
                GRAPH ?g { ?s ?p ?o }
            } GROUP BY ?g ORDER BY DESC(?triples)
            """,
            out_format="df",
        )
        if df is None or len(df) == 0:
            st.info("No named graphs in this repository.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:  # noqa: BLE001
        st.info(f"Could not list named graphs: {e}")


def _section_storage() -> None:
    st.markdown("##### 💾 Storage")

    backend = _env("STORAGE_BACKEND") or "local"
    _kv("Backend", backend)

    if backend != "local":
        nc_url = _env("NEXTCLOUD_BASE_URL")
        _kv("NextCloud base URL", nc_url or "(not set)")
        _kv("NextCloud credentials", _bool_badge(bool(_env("NEXTCLOUD_BASIC_USERNAME"))))
        browser_url = _derive_nextcloud_browser_url(nc_url)
        if browser_url:
            _kv("Browse in NextCloud", f"[{browser_url}]({browser_url})")
        return

    root = _repo_root()
    data_dir = root / "data"
    _kv("Data root", str(data_dir))

    subdirs = ["workspaces", "namespaces", "queries", "services", "ontology"]
    summary_lines = []
    for sub in subdirs:
        p = data_dir / sub
        files, size = _dir_totals(p)
        if p.exists():
            summary_lines.append(f"- **{sub}/** — {files} file(s), {_human_bytes(size)}")
        else:
            summary_lines.append(f"- **{sub}/** — ⚪ not created yet")
    st.markdown("\n".join(summary_lines))

    # File browser: one tab per subfolder.
    st.caption("Browse files (download via ⬇ button)")
    tab_labels = [f"{s}/" for s in subdirs]
    tabs = st.tabs(tab_labels)
    for tab, sub in zip(tabs, subdirs):
        with tab:
            _render_file_browser(data_dir / sub)


def _render_file_browser(path: Path) -> None:
    if not path.exists():
        st.info(f"`{path.name}/` does not exist yet.")
        return
    files, total = _list_files(path)
    if total == 0:
        st.info("Empty.")
        return

    st.caption(f"{total} file(s) — showing {len(files)}")
    for fp in files:
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        rel = fp.relative_to(path)
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"`{rel}` · {_human_bytes(size)}")
        if size <= MAX_DOWNLOAD_BYTES:
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                c2.download_button(
                    "⬇",
                    data=data,
                    file_name=fp.name,
                    key=f"dl_{fp}",
                    use_container_width=True,
                )
            except OSError:
                c2.markdown("—")
        else:
            c2.markdown("(too large)")
    if total > len(files):
        st.caption(f"… {total - len(files)} more file(s) not shown")


def _section_ontology() -> None:
    st.markdown("##### 📚 Ontology")

    onto_dir_env = _env("ONTOLOGY_DIR")
    onto_dir = Path(onto_dir_env) if onto_dir_env else (_repo_root() / "data" / "ontology")
    core = onto_dir / "dici_onto_core.ttl"
    ext_dir = onto_dir / "extensions"
    exports_dir = onto_dir / "exports"
    mappings_in = onto_dir / "mappings" / "input"

    core_status = "✅ present" if core.exists() else "❌ missing"
    core_size = _human_bytes(core.stat().st_size) if core.exists() else "—"
    ext_files = len(list(ext_dir.glob("*.ttl"))) if ext_dir.exists() else 0
    export_files = len(list(exports_dir.glob("*.ttl"))) if exports_dir.exists() else 0
    mapping_inputs = len(list(mappings_in.glob("*.ttl"))) if mappings_in.exists() else 0

    _kv("Directory", str(onto_dir))
    _kv("Core TTL", f"{core_status} ({core_size})")
    _kv("User extensions", f"{ext_files} .ttl file(s)")
    _kv("Exports", f"{export_files} .ttl file(s)")
    _kv("Mapping inputs", f"{mapping_inputs} .ttl file(s)")


def _section_optional_services() -> None:
    st.markdown("##### 🧩 Optional services")

    nc_url = _env("NEXTCLOUD_BASE_URL")
    nc_configured = bool(nc_url and _env("NEXTCLOUD_BASIC_USERNAME"))
    _kv("NextCloud storage", _bool_badge(nc_configured))
    if nc_configured:
        browser_url = _derive_nextcloud_browser_url(nc_url)
        if browser_url:
            _kv("↳ Browse UI", f"[{browser_url}]({browser_url})")

    _kv("Keycloak auth",
        _bool_badge(bool(_env("KEYCLOAK_BASE_URL") and _env("KEYCLOAK_CLIENT_ID"))))

    st.caption(
        "Credential values are never shown here. "
        "To change configuration edit `.env` and restart the container — "
        "see `.env.example` for the full set of variables."
    )


# --------------------------------------------------------------------------- #
# Entry points                                                                #
# --------------------------------------------------------------------------- #


def system_status_body(client=None) -> None:
    """Render the full System Status body (no wrapping expander).

    Used by the sidebar expander in ``app.py``. Each section is wrapped in its
    own try/except so one failure never blanks the whole page.
    """
    sections = (
        ("platform", _section_platform, ()),
        ("graphdb", _section_graphdb, (client,)),
        ("storage", _section_storage, ()),
        ("ontology", _section_ontology, ()),
        ("services", _section_optional_services, ()),
    )
    for i, (name, fn, args) in enumerate(sections):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            st.error(f"Section `{name}` failed to render: {e}")
        if i < len(sections) - 1:
            st.markdown("---")


def render_system_status_sidebar(client=None) -> None:
    """Render System Status as a single sidebar expander."""
    with st.sidebar.expander("📊 System Status"):
        system_status_body(client)


# Backwards-compatible alias in case anything still imports the module-style name.
system_status_module = system_status_body
