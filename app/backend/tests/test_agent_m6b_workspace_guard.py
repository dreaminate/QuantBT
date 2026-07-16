"""M6b path-traversal guard — ``main._agent_workspace_for_owner``.

The agent workspace (``DATA_ROOT/agent_workspaces/<owner>``) is handed to
``claude --add-dir`` = a real filesystem grant, so a hostile / malformed owner must
never make the workspace escape the ``agent_workspaces`` root. Design = cross-vendor
duet (codex B7). Two shape-independent layers: (1) a categorical single-segment
allowlist that rejects separators / ``..`` / absolute / nul before touching the FS,
and (2) resolved containment (``is_relative_to``, not a string prefix) + symlink-leaf
refusal.

Mutation contract (RULES §2 种坏门必抓):
- Drop the categorical allowlist / resolved-containment → an absolute or ``../..``
  owner produces a path outside the root → a hostile-owner case goes RED.
- Drop the symlink-leaf refusal / weaken containment to ``str.startswith`` → the
  planted-symlink escape (leaf inside the tree, target outside) is admitted → RED.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.main as main


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    # Isolate the guard's filesystem writes under tmp_path (patched DATA_ROOT).
    monkeypatch.setattr(main, "DATA_ROOT", tmp_path)
    return (tmp_path / "agent_workspaces").resolve()


@pytest.mark.parametrize(
    "owner",
    [
        "",              # empty
        ".",             # cwd
        "..",            # parent
        "/etc",          # absolute — os.path join would REPLACE the base
        "/etc/passwd",
        "../../etc",     # classic traversal
        "a/../../b",     # traversal via inner ..
        "a/b",           # embedded separator (multi-segment)
        "foo/bar",
        "..\\..",        # backslash traversal
        "x\x00y",        # nul byte
        "-flag",         # leading dash (argv-shape)
        ".hidden",       # leading dot
        "  ",            # whitespace-only
        "a" * 65,        # over the 64-char cap
    ],
)
def test_hostile_owner_rejected(owner, root):
    with pytest.raises(ValueError):
        main._agent_workspace_for_owner(owner)


@pytest.mark.parametrize(
    "owner",
    ["user-a1b2c3d4e5f6a7b8", "local", "u", "a.b_c-d", "User123", "a" * 64],
)
def test_valid_owner_returns_contained_single_segment_workspace(owner, root):
    ws = main._agent_workspace_for_owner(owner)
    resolved = ws.resolve()
    assert resolved.is_relative_to(root)  # contained
    assert resolved.parent == root        # a DIRECT child (one segment), not nested
    assert ws.is_dir() and not ws.is_symlink()


def test_planted_symlink_leaf_pointing_outside_is_rejected(tmp_path, monkeypatch):
    """A symlink whose leaf sits in the tree but resolves OUTSIDE the root → rejected.

    ``is_relative_to`` on the RESOLVED path (plus the explicit symlink-leaf refusal)
    catches an escape a string check on the owner alone would miss.
    """

    monkeypatch.setattr(main, "DATA_ROOT", tmp_path)
    root = tmp_path / "agent_workspaces"
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "evil").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        main._agent_workspace_for_owner("evil")


def test_planted_symlink_to_prefix_sibling_is_rejected(tmp_path, monkeypatch):
    """A symlink resolving to a STRING-PREFIX sibling (``agent_workspaces_evil``) is
    rejected — the case a naive ``str.startswith`` containment would wrongly admit."""

    monkeypatch.setattr(main, "DATA_ROOT", tmp_path)
    root = tmp_path / "agent_workspaces"
    root.mkdir(parents=True, exist_ok=True)
    prefix_sibling = tmp_path / "agent_workspaces_evil"  # shares the str-prefix of root
    prefix_sibling.mkdir()
    (root / "evil").symlink_to(prefix_sibling, target_is_directory=True)
    with pytest.raises(ValueError):
        main._agent_workspace_for_owner("evil")
