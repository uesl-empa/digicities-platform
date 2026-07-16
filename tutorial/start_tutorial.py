# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""One-command launcher for the Digicities tutorial.

Run from the repo root:

    python tutorial/start_tutorial.py

What it does:

1. Verifies Docker + Jupyter are installed.
2. Brings up the `fuseki` + `streamlit` compose stack if it's not already running.
3. Waits for Fuseki to report healthy on http://localhost:3030.
4. Creates the `workspace_demo` dataset if needed, loads the core ontology into
   its default graph, and loads the Alpine Village sample data into the named
   graph <https://digicities.info/tutorial/alpine_village> plus the two fixed
   graphs the Replica Builder reads.
5. If the NextCloud overlay is active and reachable, seeds the workspace
   with ontology extensions, data products, and geospatial content from
   tutorial/sample_data/nextcloud/. Silent no-op otherwise.
6. Auto-installs `jupyterlab` via pip if no Jupyter is on PATH.
7. Detects whether a Jupyter is already running that can serve the requested
   notebook (e.g. you left one open from a previous run) and just opens the
   browser to it; otherwise launches a fresh Jupyter Lab rooted at the repo
   root so both tutorial/ and data/ingestion/ notebooks are reachable. Either
   way, the browser tab is opened for you — no need to copy the URL out of
   the terminal.

Flags:

    --no-docker     Skip the docker-compose step (use if you're running Fuseki yourself).
    --no-load       Skip sample data + NextCloud seed.
    --no-nextcloud  Skip only the NextCloud seed (keep the GraphDB upload).
    --notebook N    Open a different notebook. Bare filenames resolve under
                    tutorial/ (default: 01_ontology_basics.ipynb); paths like
                    `data/ingestion/ingest.ipynb` resolve from the repo root.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252) that can't encode the
# arrows/ellipses in our progress messages, which would otherwise crash the
# launcher with UnicodeEncodeError. Force UTF-8 so it never dies on output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
TUTORIAL_DIR = Path(__file__).resolve().parent
DEFAULT_NOTEBOOK = "01_ontology_basics.ipynb"
GRAPHDB_URL = "http://localhost:3030"
REPO_NAME = "workspace_demo"
# Bare graph IRIs (no angle brackets) — the Graph Store upload helper quotes
# them into the ?graph= parameter itself.
SAMPLE_GRAPH_IRI = "https://digicities.info/tutorial/alpine_village"
# The Replica Builder UI expects its data in two fixed named graphs (see
# apps/streamlit/components/replica_builder/replica_graph_loader.py). We mirror
# Alpine Village into these so the builder's "Load Graphs" button finds
# something. The canonical tutorial graph (SAMPLE_GRAPH_IRI) is what the
# notebooks query — keep all three in sync so the UI and notebooks show the
# same data.
BUILDER_CLASSES_IRI = "http://classes_and_attributes"
BUILDER_SYSTEM_IRI = "http://system_description"
SAMPLE_TTL = TUTORIAL_DIR / "sample_data" / "alpine_village.ttl"
# Core ontology, loaded into the tutorial dataset's default graph so the
# notebooks' clause-less ontology queries resolve.
CORE_TTL = REPO_ROOT / "services" / "graphdb" / "ontology" / "dici_onto_core.ttl"

# NextCloud seed content. Uploaded when the overlay is active. Layout:
#   nextcloud/ontology_extensions/*.ttl  → {workspace}/ontology/extensions/
#   nextcloud/data_products/*            → {workspace}/private_data_products/
NEXTCLOUD_SEED_DIR = TUTORIAL_DIR / "sample_data" / "nextcloud"
# Host-side URL for WebDAV reachability. `docker-compose.nextcloud.yml`
# exposes NextCloud on port 8080; the Streamlit container talks to
# http://nextcloud:80 internally but the launcher runs on the host.
NEXTCLOUD_HOST_URL = "http://localhost:8080"


def info(msg: str) -> None:
    print(f"[tutorial] {msg}")


def die(msg: str, code: int = 1) -> None:
    print(f"[tutorial] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def check_tool(name: str, hint: str) -> str:
    path = shutil.which(name)
    if not path:
        die(f"`{name}` not found on PATH. {hint}")
    return path


def docker_compose_cmd() -> list[str]:
    """Return the working docker-compose command (`docker compose` vs legacy `docker-compose`)."""
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True, capture_output=True, text=True,
        )
        return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    die("Docker Compose not found. Install Docker Desktop and retry.")
    return []  # unreachable


def ensure_stack_up(compose: list[str]) -> None:
    ps = subprocess.run(
        compose + ["ps", "--services", "--filter", "status=running"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    running = set(ps.stdout.split())
    if {"fuseki", "streamlit"}.issubset(running):
        info("compose stack already running")
        return
    info("starting docker compose stack (this can take a minute on first run)…")
    subprocess.run(compose + ["up", "-d"], cwd=REPO_ROOT, check=True)


def wait_for_triplestore(timeout_s: int = 180) -> None:
    """Poll Fuseki's admin ping endpoint until it reports healthy.

    Fuseki serves 200 on /$/ping once the server is up. The tutorial dataset
    itself is created later by load_sample_data(), so we only wait for the
    server here, not for a specific dataset.
    """
    info(f"waiting for Fuseki at {GRAPHDB_URL} …")
    deadline = time.time() + timeout_s
    url = f"{GRAPHDB_URL}/$/ping"
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    info("Fuseki healthy")
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
        time.sleep(3)
    die(f"Fuseki did not come up within {timeout_s}s (last error: {last_err})")


def load_sample_data() -> None:
    if not SAMPLE_TTL.exists():
        die(f"sample TTL missing: {SAMPLE_TTL}")

    # Select the Fuseki backend + admin creds *before* importing the backend —
    # get_backend() reads these at call time. They match the docker-compose
    # defaults; override by exporting them or setting them in .env. Fuseki needs
    # HTTP Basic admin auth for dataset creation and all writes.
    import os
    os.environ.setdefault("TRIPLESTORE_BACKEND", "fuseki")
    os.environ.setdefault("GRAPHDB_URL", GRAPHDB_URL)
    os.environ.setdefault("FUSEKI_URL", GRAPHDB_URL)
    os.environ.setdefault("FUSEKI_ADMIN_USER", "admin")
    os.environ.setdefault("FUSEKI_ADMIN_PASSWORD", "admin")

    # Import lazily so --no-load users don't need the backend installed.
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from backend.workspace.graphdb_provisioning import (
            create_repository,
            upload_ttl_to_graph,
        )
    except ImportError as e:
        die(
            "Could not import `backend.workspace.graphdb_provisioning`. Run "
            "`pip install -e .` from the repo root, or re-run with --no-load. "
            f"(import error: {e})"
        )
        return

    # 1) Make sure the tutorial dataset exists (idempotent).
    info(f"ensuring Fuseki dataset `{REPO_NAME}` exists")
    if not create_repository(REPO_NAME, "Digicities tutorial sandbox"):
        die(
            f"could not create/verify Fuseki dataset `{REPO_NAME}` — is the "
            "stack up and are the admin credentials correct?"
        )

    # 2) Core ontology → default graph. The notebooks query the ontology with
    #    clause-less SPARQL (no GRAPH { … }), so it must sit in this tutorial
    #    dataset's default graph. (Instances go into named graphs below.)
    if CORE_TTL.exists():
        info(f"loading core ontology → default graph  [{CORE_TTL.name}]")
        if not upload_ttl_to_graph(
            REPO_NAME, "", CORE_TTL.read_text(encoding="utf-8"), replace=True
        ):
            die("core ontology upload failed — check Fuseki admin credentials")
    else:
        info(
            f"WARNING: core ontology TTL missing ({CORE_TTL}) — the ontology "
            "cells in notebook 01 will come back empty"
        )

    # 3) Alpine Village → three named graphs:
    #   - SAMPLE_GRAPH_IRI: what the notebooks query.
    #   - BUILDER_CLASSES_IRI / BUILDER_SYSTEM_IRI: what the Streamlit Replica
    #     Builder's "Load Graphs" button reads (those graph IRIs are hard-coded
    #     in replica_graph_loader.py).
    # Cheap at ~130 triples and means the UI and notebooks show the same data.
    ttl = SAMPLE_TTL.read_text(encoding="utf-8")
    targets = [
        (SAMPLE_GRAPH_IRI, "tutorial graph (notebooks)"),
        (BUILDER_CLASSES_IRI, "classes_and_attributes (Replica Builder instances)"),
        (BUILDER_SYSTEM_IRI, "system_description (Replica Builder links)"),
    ]
    for graph_iri, purpose in targets:
        info(f"loading {SAMPLE_TTL.name} → <{graph_iri}>  [{purpose}]")
        if not upload_ttl_to_graph(REPO_NAME, graph_iri, ttl, replace=True):
            info(f"   WARN: upload to <{graph_iri}> failed (non-fatal)")
    info("Alpine Village loaded")


# --------------------------------------------------------------------------- #
# NextCloud seeding                                                           #
# --------------------------------------------------------------------------- #


def _nextcloud_creds() -> tuple[str, str] | None:
    """Return (user, password) if the NextCloud overlay creds are set, else None."""
    import os
    user = os.environ.get("NEXTCLOUD_BASIC_USERNAME")
    pwd = os.environ.get("NEXTCLOUD_BASIC_PASSWORD")
    if user and pwd:
        return user, pwd
    # Fall back to reading .env directly — docker-compose.nextcloud.yml injects
    # these into the Streamlit container, but the host-side launcher doesn't
    # get them unless the user exports them too.
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        vals = {}
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
        if vals.get("NEXTCLOUD_BASIC_USERNAME") and vals.get("NEXTCLOUD_BASIC_PASSWORD"):
            return vals["NEXTCLOUD_BASIC_USERNAME"], vals["NEXTCLOUD_BASIC_PASSWORD"]
    return None


def _nextcloud_reachable(user: str, pwd: str) -> bool:
    """Probe the admin user's WebDAV root with basic auth."""
    import base64
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    url = f"{NEXTCLOUD_HOST_URL}/remote.php/dav/files/{user}/"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Basic {token}"}, method="PROPFIND",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            # WebDAV PROPFIND returns 207 Multi-Status on success
            return resp.status in (200, 207)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def _webdav_put(user: str, pwd: str, rel_path: str, data: bytes) -> int:
    import base64
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    url = f"{NEXTCLOUD_HOST_URL}/remote.php/dav/files/{user}/{rel_path}"
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _webdav_mkcol(user: str, pwd: str, rel_path: str) -> int:
    import base64
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    url = f"{NEXTCLOUD_HOST_URL}/remote.php/dav/files/{user}/{rel_path.rstrip('/')}/"
    req = urllib.request.Request(
        url, method="MKCOL",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def seed_nextcloud_workspace() -> None:
    """Upload tutorial seed files to NextCloud if the overlay is running.

    Silent no-op if NextCloud isn't configured — so this function is safe to
    call unconditionally. All uploads are idempotent (PUT replaces, MKCOL on
    existing folder returns 405 which we treat as success).
    """
    if not NEXTCLOUD_SEED_DIR.exists():
        info("no NextCloud seed content on disk — skipping")
        return

    creds = _nextcloud_creds()
    if not creds:
        info("NextCloud creds not in env or .env — skipping NextCloud seed")
        return
    user, pwd = creds

    if not _nextcloud_reachable(user, pwd):
        info(f"NextCloud not reachable at {NEXTCLOUD_HOST_URL} — skipping seed "
             "(start the overlay with the NextCloud COMPOSE_FILE in .env)")
        return

    info(f"seeding NextCloud workspace '{REPO_NAME}' as user '{user}'")

    # --- Ontology extensions ---
    ext_src = NEXTCLOUD_SEED_DIR / "ontology_extensions"
    if ext_src.exists():
        # Ensure the extensions folder exists (init sidecar should have created
        # it, but we're defensive in case the user is seeding a pre-existing
        # NextCloud).
        _webdav_mkcol(user, pwd, f"{REPO_NAME}/ontology")
        _webdav_mkcol(user, pwd, f"{REPO_NAME}/ontology/extensions")
        for ttl in sorted(ext_src.glob("*.ttl")):
            rel = f"{REPO_NAME}/ontology/extensions/{ttl.name}"
            code = _webdav_put(user, pwd, rel, ttl.read_bytes())
            info(f"   ontology ext  [{code}]  {ttl.name}")

    # --- Data products ---
    dp_src = NEXTCLOUD_SEED_DIR / "data_products"
    if dp_src.exists():
        _webdav_mkcol(user, pwd, f"{REPO_NAME}/private_data_products")
        for product_dir in sorted(d for d in dp_src.iterdir() if d.is_dir()):
            dest_root = f"{REPO_NAME}/private_data_products/{product_dir.name}"
            _webdav_mkcol(user, pwd, dest_root)
            _webdav_mkcol(user, pwd, f"{dest_root}/resources")
            uploaded = 0
            for file_path in product_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(product_dir).as_posix()
                code = _webdav_put(user, pwd, f"{dest_root}/{rel}", file_path.read_bytes())
                if 200 <= code < 300:
                    uploaded += 1
                else:
                    info(f"   WARN[{code}]  {rel}")
            info(f"   data product  {product_dir.name}: {uploaded} file(s)")

    # --- Scenarios ---
    sc_src = NEXTCLOUD_SEED_DIR / "scenarios"
    if sc_src.exists():
        _webdav_mkcol(user, pwd, f"{REPO_NAME}/scenarios")
        for ttl in sorted(sc_src.glob("*.ttl")):
            rel = f"{REPO_NAME}/scenarios/{ttl.name}"
            code = _webdav_put(user, pwd, rel, ttl.read_bytes())
            info(f"   scenario      [{code}]  {ttl.name}")

    # --- Services ---
    svc_src = NEXTCLOUD_SEED_DIR / "services"
    if svc_src.exists():
        _webdav_mkcol(user, pwd, f"{REPO_NAME}/services")
        for svc in sorted(svc_src.iterdir()):
            if not svc.is_file():
                continue
            rel = f"{REPO_NAME}/services/{svc.name}"
            code = _webdav_put(user, pwd, rel, svc.read_bytes())
            info(f"   service       [{code}]  {svc.name}")

    info("NextCloud seed complete — browse at http://localhost:8080 (user: "
         f"{user})")


def _jupyter_subcommand_ok(sub: str) -> bool:
    """True if `jupyter <sub> --version` runs successfully."""
    try:
        r = subprocess.run(
            ["jupyter", sub, "--version"],
            capture_output=True, text=True, check=False,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def ensure_jupyter() -> None:
    """Make sure `jupyter lab` (or at least `jupyter notebook`) is runnable.

    If neither is available, pip-install `jupyterlab` into the current Python
    environment and re-check. The tutorial is useless without Jupyter, so we
    treat this as part of setup rather than bailing out.
    """
    if _jupyter_subcommand_ok("lab") or _jupyter_subcommand_ok("notebook"):
        return
    info("Jupyter not found — installing `jupyterlab` into the current environment (first run only)…")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "jupyterlab"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        die(
            "pip install jupyterlab failed. Install it manually "
            f"(`{sys.executable} -m pip install jupyterlab`) and retry. ({e})"
        )
    if not _jupyter_subcommand_ok("lab"):
        die(
            "Jupyter Lab still isn't runnable after install. "
            "Check that `jupyter` resolves to the same Python interpreter as "
            f"`{sys.executable}`."
        )


def _resolve_notebook(notebook: str) -> Path:
    """Resolve `--notebook` to an absolute path.

    Accepts bare filenames (resolved relative to tutorial/), relative paths
    like `../data/ingestion/ingest.ipynb`, or absolute paths.
    """
    p = Path(notebook)
    if p.is_absolute() and p.exists():
        return p.resolve()
    # Try tutorial/ first (covers the bare-filename default), then repo root.
    for base in (TUTORIAL_DIR, REPO_ROOT):
        candidate = (base / notebook).resolve()
        if candidate.exists():
            return candidate
    die(f"notebook not found: tried tutorial/{notebook} and {notebook}")
    return Path()  # unreachable


def _list_running_jupyters():
    """Return a list of dicts describing every Jupyter server we can see.

    Reads the connection files Jupyter writes under its runtime dir. Empty
    list if jupyter_server isn't importable (Jupyter not installed).
    """
    try:
        from jupyter_server.serverapp import list_running_servers
    except ImportError:
        return []
    return list(list_running_servers())


def _find_jupyter_serving(notebook_path: Path):
    """Return the first running Jupyter whose root_dir contains notebook_path."""
    notebook_path = notebook_path.resolve()
    for srv in _list_running_jupyters():
        root = Path(srv.get("root_dir") or srv.get("notebook_dir") or ".").resolve()
        try:
            notebook_path.relative_to(root)
            return srv
        except ValueError:
            continue
    return None


def _notebook_url(server: dict, notebook_path: Path) -> str:
    """Build a /lab/tree/<rel> URL pointing at notebook_path within server."""
    root = Path(server.get("root_dir") or server.get("notebook_dir", ".")).resolve()
    try:
        rel = notebook_path.resolve().relative_to(root).as_posix()
    except ValueError:
        rel = ""
    base = server["url"].rstrip("/") + "/lab"
    if rel:
        base += "/tree/" + rel
    token = server.get("token")
    if token:
        base += "?token=" + token
    return base


def _open_browser(url: str) -> None:
    info(f"opening browser: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:  # webbrowser can fail silently on headless WSL etc.
        info(f"webbrowser.open failed: {e}")
    info("(if a tab didn't open, paste the URL above into your browser)")


def _open_browser_when_ready(notebook_path: Path, max_wait_s: int = 20) -> None:
    """Background-thread poll for our new Jupyter, open browser when it appears."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        time.sleep(1)
        srv = _find_jupyter_serving(notebook_path)
        if srv:
            _open_browser(_notebook_url(srv, notebook_path))
            return
    info(f"timed out after {max_wait_s}s waiting for Jupyter to publish its URL")
    info("the URL will appear in the Jupyter output below — copy it into your browser.")


def launch_jupyter(notebook: str) -> None:
    target = _resolve_notebook(notebook)

    # If a Jupyter is already serving a directory that contains the target
    # notebook, just open the browser to it instead of spawning another one.
    existing = _find_jupyter_serving(target)
    if existing:
        info(f"reusing existing Jupyter at {existing['url']} (PID {existing.get('pid', '?')})")
        _open_browser(_notebook_url(existing, target))
        info("(this Jupyter is owned by another terminal — close that one if you want to stop it)")
        return

    # Otherwise spawn a fresh Jupyter Lab rooted at the repo root so it can
    # serve both tutorial/ and data/ingestion/ notebooks.
    sub = "lab" if _jupyter_subcommand_ok("lab") else "notebook"
    rel_target = target.relative_to(REPO_ROOT).as_posix()
    cmd = ["jupyter", sub, rel_target]
    info(f"launching: {' '.join(cmd)}  (root: {REPO_ROOT})")
    info("(Ctrl-C in this terminal stops Jupyter.)")

    # Open the browser in a background thread once Jupyter has published its
    # connection info. subprocess.run below blocks until Jupyter exits.
    threading.Thread(
        target=_open_browser_when_ready,
        args=(target,),
        daemon=True,
    ).start()

    subprocess.run(cmd, cwd=REPO_ROOT, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Digicities tutorial.")
    parser.add_argument("--no-docker", action="store_true",
                        help="skip docker-compose (use if you're running GraphDB another way)")
    parser.add_argument("--no-load", action="store_true",
                        help="skip loading the Alpine Village sample data (and the NextCloud seed)")
    parser.add_argument("--no-nextcloud", action="store_true",
                        help="skip the NextCloud seed step even when the overlay is running")
    parser.add_argument("--notebook", default=DEFAULT_NOTEBOOK,
                        help=f"notebook to open (default: {DEFAULT_NOTEBOOK})")
    args = parser.parse_args()

    if not args.no_docker:
        check_tool("docker", "Install Docker Desktop from https://docker.com.")
        compose = docker_compose_cmd()
        ensure_stack_up(compose)
        wait_for_triplestore()
    else:
        info("--no-docker set, skipping compose step")
        wait_for_triplestore()

    if not args.no_load:
        load_sample_data()
        if not args.no_nextcloud:
            seed_nextcloud_workspace()
    else:
        info("--no-load set, skipping sample-data upload (and NextCloud seed)")

    ensure_jupyter()
    launch_jupyter(args.notebook)


if __name__ == "__main__":
    main()
