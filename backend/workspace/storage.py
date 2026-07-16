# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Storage abstraction over a single workspace, built on fsspec.

A `WorkspaceStorage` wraps an fsspec `AbstractFileSystem` plus a root path. It
exposes I/O methods that take *workspace-relative* paths (e.g.
`ontology/extensions/foo.ttl`) and resolves them against the root.

The canonical layout (see docs/WORKSPACE_LAYOUT.md) is fixed; this class
exposes shortcut properties for the well-known subpaths so module code reads
naturally:

    storage.ontology.extensions      # → "{root}/ontology/extensions"
    storage.ingestion.input          # → "{root}/ingestion/input"
    storage.scenarios                # → "{root}/scenarios"

Two filesystem backends are exercised in v0.2:

- `local` — plain disk path. Backed by fsspec's `LocalFileSystem`.
- `nextcloud` — WebDAV. Backed by fsspec's `webdav` filesystem
  (`pip install webdav4[fsspec]`).

Other fsspec backends (S3, GCS, FTP, …) work in principle without code changes
— register them in workspaces.yaml with `backend: fsspec` + `protocol: <name>`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterator, Optional

import fsspec
from fsspec.spec import AbstractFileSystem


# ---------------------------------------------------------------------------
# Canonical layout — the only place these path fragments are defined.
# ---------------------------------------------------------------------------

ONTOLOGY_EXTENSIONS   = "ontology/extensions"
ONTOLOGY_EXPORTS      = "ontology/exports"
ONTOLOGY_TEMP         = "ontology/temp"
ONTOLOGY_MAPPINGS_IN  = "ontology/mappings/input"
ONTOLOGY_MAPPINGS_OUT = "ontology/mappings/output"

INGESTION_INPUT       = "ingestion/input"
INGESTION_OUTPUT      = "ingestion/output"

SCENARIOS             = "scenarios"
SERVICES              = "services"
QUERIES               = "queries"
PRIVATE_DATA_PRODUCTS = "private_data_products"
TIMESERIES            = "timeseries"
NOTEBOOKS             = "notebooks"
DOCS                  = "docs"
WORKSPACE_META        = "workspace_meta"

CANONICAL_SUBDIRS = [
    ONTOLOGY_EXTENSIONS, ONTOLOGY_EXPORTS, ONTOLOGY_TEMP,
    ONTOLOGY_MAPPINGS_IN, ONTOLOGY_MAPPINGS_OUT,
    INGESTION_INPUT, INGESTION_OUTPUT,
    SCENARIOS, SERVICES, QUERIES,
    PRIVATE_DATA_PRODUCTS, TIMESERIES,
    NOTEBOOKS, DOCS, WORKSPACE_META,
]


# ---------------------------------------------------------------------------
# Convenience namespaces — let module code write storage.ontology.extensions
# instead of constants. Cheap; just dotted accessors over the constants above.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _OntologyPaths:
    extensions:    str = ONTOLOGY_EXTENSIONS
    exports:       str = ONTOLOGY_EXPORTS
    temp:          str = ONTOLOGY_TEMP
    mappings_in:   str = ONTOLOGY_MAPPINGS_IN
    mappings_out:  str = ONTOLOGY_MAPPINGS_OUT


@dataclass(frozen=True)
class _IngestionPaths:
    input:  str = INGESTION_INPUT
    output: str = INGESTION_OUTPUT


# ---------------------------------------------------------------------------
# WorkspaceStorage
# ---------------------------------------------------------------------------

class WorkspaceStorage:
    """fsspec-backed I/O for one workspace.

    Construct via `WorkspaceStorage.local(path)` or `WorkspaceStorage.webdav(...)`
    or the generic `WorkspaceStorage.from_fsspec(protocol, root, **opts)`.
    """

    ontology  = _OntologyPaths()
    ingestion = _IngestionPaths()
    scenarios             = SCENARIOS
    services              = SERVICES
    queries               = QUERIES
    private_data_products = PRIVATE_DATA_PRODUCTS
    timeseries            = TIMESERIES
    notebooks             = NOTEBOOKS
    docs                  = DOCS
    workspace_meta        = WORKSPACE_META

    def __init__(self, fs: AbstractFileSystem, root: str, protocol: str):
        """Use the factory classmethods rather than calling __init__ directly."""
        self.fs = fs
        # Normalise to forward slashes so glob results (which fsspec returns
        # forward-slashed even on Windows) can be stripped consistently.
        self.root = root.replace("\\", "/").rstrip("/")
        self.protocol = protocol

    # ---- factories -------------------------------------------------------

    @classmethod
    def local(cls, path: str) -> "WorkspaceStorage":
        fs = fsspec.filesystem("file")
        return cls(fs, path, "file")

    @classmethod
    def webdav(
        cls,
        base_url: str,
        username: str,
        password: str,
        root: str,
    ) -> "WorkspaceStorage":
        """NextCloud workspace via WebDAV.

        Requires `pip install webdav4[fsspec]`.
        `root` is the workspace folder path on the NextCloud user account,
        e.g. "motel-energy" → addresses /remote.php/dav/files/<user>/motel-energy/...
        """
        try:
            import webdav4.fsspec  # noqa: F401  — registers the 'webdav' protocol
        except ImportError as exc:
            raise RuntimeError(
                "WebDAV/NextCloud workspaces need webdav4[fsspec]. "
                "Run `pip install webdav4[fsspec]`."
            ) from exc

        fs = fsspec.filesystem(
            "webdav",
            base_url=base_url.rstrip("/"),
            auth=(username, password),
        )
        return cls(fs, root, "webdav")

    @classmethod
    def from_fsspec(cls, protocol: str, root: str, **opts) -> "WorkspaceStorage":
        """Generic factory for any fsspec-registered filesystem (s3, gcs, …)."""
        fs = fsspec.filesystem(protocol, **opts)
        return cls(fs, root, protocol)

    # ---- path resolution -------------------------------------------------

    def _abs(self, rel: str) -> str:
        rel = rel.lstrip("/")
        return f"{self.root}/{rel}" if rel else self.root

    # ---- I/O — workspace-relative paths everywhere -----------------------

    def exists(self, rel_path: str) -> bool:
        return self.fs.exists(self._abs(rel_path))

    def isdir(self, rel_path: str) -> bool:
        return self.fs.isdir(self._abs(rel_path))

    def ls(self, rel_path: str, detail: bool = False) -> list:
        path = self._abs(rel_path)
        if not self.fs.exists(path):
            return []
        return self.fs.ls(path, detail=detail)

    def glob(self, rel_pattern: str) -> list[str]:
        """Returns workspace-relative paths matching the pattern.

        fsspec normalises results to forward slashes even on Windows, so we
        normalise both sides before stripping the root prefix.
        """
        results = self.fs.glob(self._abs(rel_pattern))
        root_prefix = self.root.rstrip("/") + "/"
        out = []
        for r in results:
            r_norm = r.replace("\\", "/")
            if r_norm.startswith(root_prefix):
                out.append(r_norm[len(root_prefix):])
            else:
                out.append(r_norm)
        return out

    def read_text(self, rel_path: str, encoding: str = "utf-8") -> str:
        with self.fs.open(self._abs(rel_path), "r", encoding=encoding) as f:
            return f.read()

    def read_bytes(self, rel_path: str) -> bytes:
        with self.fs.open(self._abs(rel_path), "rb") as f:
            return f.read()

    def write_text(self, rel_path: str, content: str, encoding: str = "utf-8") -> None:
        self._ensure_parent(rel_path)
        with self.fs.open(self._abs(rel_path), "w", encoding=encoding) as f:
            f.write(content)

    def write_bytes(self, rel_path: str, content: bytes) -> None:
        self._ensure_parent(rel_path)
        with self.fs.open(self._abs(rel_path), "wb") as f:
            f.write(content)

    def delete(self, rel_path: str) -> None:
        if self.fs.exists(self._abs(rel_path)):
            self.fs.rm(self._abs(rel_path))

    def mkdir(self, rel_path: str, exist_ok: bool = True) -> None:
        path = self._abs(rel_path)
        if self.fs.exists(path):
            if exist_ok:
                return
            raise FileExistsError(path)
        self.fs.makedirs(path, exist_ok=True)

    def _ensure_parent(self, rel_path: str) -> None:
        parent = str(PurePosixPath(rel_path).parent)
        if parent and parent != ".":
            self.mkdir(parent, exist_ok=True)

    # ---- canonical layout bootstrap --------------------------------------

    def ensure_canonical_layout(self) -> list[str]:
        """Create any missing canonical subdirs. Returns the list of created dirs.

        Idempotent — safe to call on every workspace open.
        """
        created = []
        for sub in CANONICAL_SUBDIRS:
            if not self.exists(sub):
                self.mkdir(sub, exist_ok=True)
                created.append(sub)
        return created

    # ---- iteration helpers used by modules -------------------------------

    def iter_ttl_files(self, rel_dir: str) -> Iterator[str]:
        """Yield workspace-relative paths of every *.ttl file under rel_dir."""
        yield from self.glob(f"{rel_dir}/*.ttl")

    # ---- introspection ---------------------------------------------------

    def __repr__(self) -> str:
        return f"<WorkspaceStorage protocol={self.protocol!r} root={self.root!r}>"
