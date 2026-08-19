# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""workspace_last_updated: the landing page's 'last worked on' signal."""
from __future__ import annotations

import os
import time

from backend.workspace import workspace_last_updated


def test_newest_file_wins(tmp_path):
    old = tmp_path / "ontology" / "extensions"
    old.mkdir(parents=True)
    f_old = old / "a.ttl"
    f_old.write_text("old")
    t_old = time.time() - 86400
    os.utime(f_old, (t_old, t_old))

    new = tmp_path / "scenarios"
    new.mkdir()
    f_new = new / "baseline.ttl"
    f_new.write_text("new")
    t_new = time.time() - 60
    os.utime(f_new, (t_new, t_new))

    latest = workspace_last_updated(tmp_path)
    assert latest is not None
    assert abs(latest - t_new) < 2


def test_hidden_dirs_skipped(tmp_path):
    (tmp_path / "docs").mkdir()
    visible = tmp_path / "docs" / "x.md"
    visible.write_text("x")
    t_vis = time.time() - 3600
    os.utime(visible, (t_vis, t_vis))

    git = tmp_path / ".git"
    git.mkdir()
    noisy = git / "index"
    noisy.write_text("churn")           # freshest file, but tooling noise

    latest = workspace_last_updated(tmp_path)
    assert latest is not None
    assert abs(latest - t_vis) < 2, "hidden-dir churn leaked into the stamp"


def test_empty_or_missing_returns_none(tmp_path):
    assert workspace_last_updated(tmp_path / "nope") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert workspace_last_updated(empty) is None
