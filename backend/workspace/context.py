# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Per-session workspace context.

A `WorkspaceContext` is the single object every module reaches for to know
which workspace is currently active. It bundles:

- The workspace id (stable identifier, used as the GraphDB repo name and the
  workspace_meta path)
- A friendly name (for the UI)
- A `WorkspaceStorage` for file I/O
- The chosen GraphDB repository name (defaults to the id but can be overridden)

In Streamlit, the active context lives in `st.session_state.workspace_context`
and is constructed from a workspaces.yaml entry by `WorkspaceRegistry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .storage import WorkspaceStorage


@dataclass
class WorkspaceContext:
    id: str
    name: str
    storage: WorkspaceStorage
    graphdb_repository: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.graphdb_repository:
            self.graphdb_repository = self.id

    @property
    def storage_backend(self) -> str:
        return self.storage.protocol

    def __repr__(self) -> str:
        return (
            f"<WorkspaceContext id={self.id!r} name={self.name!r} "
            f"backend={self.storage_backend!r} "
            f"graphdb_repository={self.graphdb_repository!r}>"
        )
