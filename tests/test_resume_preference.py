"""Tests for resume-preference scheduling and the underlying git helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from claw_forge.git import branch_age_in_commits, branch_has_commits_ahead
from claw_forge.state.scheduler import Scheduler, TaskNode

# ── branch_age_in_commits ────────────────────────────────────────────────────


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def test_branch_age_in_commits_returns_zero_for_fresh_branch(tmp_path: Path) -> None:
    """A branch cut from main returns 0 if main hasn't moved."""
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)
    _run(["git", "checkout", "-qb", "feat/x"], tmp_path)

    assert branch_age_in_commits(tmp_path, "feat/x", "main") == 0


def test_branch_age_in_commits_counts_main_commits_after_cut(tmp_path: Path) -> None:
    """When main moves N commits ahead, the helper returns N."""
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "a").write_text("1")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)
    _run(["git", "checkout", "-qb", "feat/x"], tmp_path)
    _run(["git", "checkout", "-q", "main"], tmp_path)
    for i in range(3):
        (tmp_path / f"m{i}").write_text(str(i))
        _run(["git", "add", "."], tmp_path)
        _run(["git", "commit", "-qm", f"m{i}"], tmp_path)

    assert branch_age_in_commits(tmp_path, "feat/x", "main") == 3


def test_branch_age_in_commits_returns_zero_on_unknown_branch(tmp_path: Path) -> None:
    """Missing branch returns 0 (treat as 'no staleness signal')."""
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "a").write_text("1")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)

    assert branch_age_in_commits(tmp_path, "feat/nonexistent", "main") == 0


# ── Scheduler sort: priority dominates, resumable breaks ties ────────────────


def test_scheduler_resumable_breaks_priority_tie() -> None:
    """At equal priority, resumable task is dispatched first."""
    s = Scheduler()
    s.add_task(TaskNode(
        id="fresh", plugin_name="coding", priority=1, depends_on=[],
        status="pending", resumable=False,
    ))
    s.add_task(TaskNode(
        id="resumable", plugin_name="coding", priority=1, depends_on=[],
        status="pending", resumable=True,
    ))

    ready = s.get_ready_tasks()
    assert [t.id for t in ready] == ["resumable", "fresh"]


def test_scheduler_priority_still_dominates_resumable() -> None:
    """A higher-priority fresh task wins over a lower-priority resumable one."""
    s = Scheduler()
    s.add_task(TaskNode(
        id="lowpri-resumable", plugin_name="coding", priority=1, depends_on=[],
        status="pending", resumable=True,
    ))
    s.add_task(TaskNode(
        id="highpri-fresh", plugin_name="coding", priority=10, depends_on=[],
        status="pending", resumable=False,
    ))

    ready = s.get_ready_tasks()
    # Priority 10 still beats priority 1 even though the lower-priority one
    # is resumable — priority dominates.
    assert [t.id for t in ready] == ["highpri-fresh", "lowpri-resumable"]


def test_scheduler_default_resumable_false_preserves_old_ordering() -> None:
    """Unspecified resumable defaults to False so existing call-sites keep behaviour."""
    s = Scheduler()
    s.add_task(TaskNode(
        id="a", plugin_name="coding", priority=1, depends_on=[], status="pending",
    ))
    s.add_task(TaskNode(
        id="b", plugin_name="coding", priority=2, depends_on=[], status="pending",
    ))
    ready = s.get_ready_tasks()
    # Highest priority first; tie-break by insertion order is irrelevant here.
    assert [t.id for t in ready] == ["b", "a"]


# ── _decorate_resumable: integration with git state ──────────────────────────


def test_decorate_resumable_marks_pending_with_committed_branch(tmp_path: Path) -> None:
    """A pending task whose feature branch has commits ahead is marked resumable."""
    from claw_forge.cli import _decorate_resumable

    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)
    # Build a feature branch with one commit ahead.  Slug must match
    # make_branch_name(description, category, plugin) — simplest path is to
    # pre-compute it from the same description we'll pass.
    from claw_forge.git.slug import make_branch_name
    branch = make_branch_name("Add login flow", "auth", "coding", prefix="feat")
    _run(["git", "checkout", "-qb", branch], tmp_path)
    (tmp_path / "f.txt").write_text("y")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "wip"], tmp_path)
    _run(["git", "checkout", "-q", "main"], tmp_path)

    node = TaskNode(
        id="t1", plugin_name="coding", priority=1, depends_on=[],
        status="pending", category="auth", description="Add login flow",
    )
    _decorate_resumable([node], tmp_path, "main", "feat")
    assert node.resumable is True


def test_decorate_resumable_skips_when_branch_missing(tmp_path: Path) -> None:
    """No feature branch → resumable stays False."""
    from claw_forge.cli import _decorate_resumable

    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)

    node = TaskNode(
        id="t1", plugin_name="coding", priority=1, depends_on=[],
        status="pending", category="auth", description="Add login flow",
    )
    _decorate_resumable([node], tmp_path, "main", "feat")
    assert node.resumable is False


def test_decorate_resumable_skips_stale_branch(tmp_path: Path) -> None:
    """A branch behind main by more than the threshold isn't preferred."""
    from claw_forge.cli import _decorate_resumable
    from claw_forge.git.slug import make_branch_name

    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)
    branch = make_branch_name("Add x", "auth", "coding", prefix="feat")
    _run(["git", "checkout", "-qb", branch], tmp_path)
    (tmp_path / "f.txt").write_text("y")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "wip"], tmp_path)
    _run(["git", "checkout", "-q", "main"], tmp_path)
    # Move main 5 commits ahead.
    for i in range(5):
        (tmp_path / f"m{i}").write_text(str(i))
        _run(["git", "add", "."], tmp_path)
        _run(["git", "commit", "-qm", f"m{i}"], tmp_path)

    node = TaskNode(
        id="t1", plugin_name="coding", priority=1, depends_on=[],
        status="pending", category="auth", description="Add x",
    )
    # threshold=3 → 5 ahead is too stale → don't mark resumable.
    _decorate_resumable([node], tmp_path, "main", "feat", stale_threshold=3)
    assert node.resumable is False
    # threshold=10 → 5 ahead is fine → mark resumable.
    _decorate_resumable([node], tmp_path, "main", "feat", stale_threshold=10)
    assert node.resumable is True


def test_decorate_resumable_disabled_is_noop() -> None:
    """When enabled=False, no nodes are marked even if their branches have commits."""
    from claw_forge.cli import _decorate_resumable

    node = TaskNode(
        id="t1", plugin_name="coding", priority=1, depends_on=[],
        status="pending",
    )
    # Use a fake project_dir; with enabled=False the function should not call git.
    fake_dir = MagicMock(spec=Path)
    with patch("claw_forge.git.branch_exists") as mock_exists:
        _decorate_resumable([node], fake_dir, "main", "feat", enabled=False)
    mock_exists.assert_not_called()
    assert node.resumable is False


def test_decorate_resumable_skips_terminal_status(tmp_path: Path) -> None:
    """Completed/failed tasks aren't checked — they aren't dispatched again."""
    from claw_forge.cli import _decorate_resumable

    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@x"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-qm", "init"], tmp_path)

    completed = TaskNode(
        id="c", plugin_name="coding", priority=1, depends_on=[], status="completed",
    )
    failed = TaskNode(
        id="f", plugin_name="coding", priority=1, depends_on=[], status="failed",
    )
    _decorate_resumable([completed, failed], tmp_path, "main", "feat")
    assert completed.resumable is False
    assert failed.resumable is False


# ── branch_has_commits_ahead is re-exported (sanity) ──────────────────────────


def test_branch_has_commits_ahead_reexported() -> None:
    """branch_has_commits_ahead is exposed via claw_forge.git for callers."""
    assert callable(branch_has_commits_ahead)
