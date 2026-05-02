"""Tests for ``claw_forge.git.cleanup`` — smart-mode worktree cleanup."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import branch_exists, create_worktree
from claw_forge.git.cleanup import (
    CleanupOutcome,
    decide_action,
    smart_cleanup_worktrees,
)
from claw_forge.git.commits import commit_checkpoint


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.x"], cwd=tmp_path, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, check=True,
    )
    (tmp_path / "README.md").write_text("# init\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True,
    )
    return tmp_path


def _task(
    *,
    description: str,
    category: str | None = None,
    plugin: str = "coding",
    status: str = "pending",
) -> dict[str, object]:
    return {
        "description": description,
        "category": category,
        "plugin_name": plugin,
        "status": status,
    }


def _make_worktree_with_commit(
    project: Path, slug: str, *, msg: str = "feat: change",
) -> tuple[str, Path]:
    branch, wt = create_worktree(project, f"task-{slug}", slug)
    (wt / f"{slug}.py").write_text(f"# {slug}\n")
    commit_checkpoint(
        wt, message=msg,
        task_id=f"task-{slug}", plugin="coding", phase="coding",
        session_id="s1",
    )
    return branch, wt


class TestDecideAction:
    """Pure-logic decision matrix; no filesystem.

    Mirrors the table in ``cleanup.py``'s module docstring.
    """

    @pytest.mark.parametrize(
        "task_status,has_commits,expected",
        [
            # No commits → always remove (nothing to keep).
            (None, False, "remove"),
            ("pending", False, "remove"),
            ("failed", False, "remove"),
            ("completed", False, "remove"),
            ("running", False, "remove"),
            # Has commits + retry-pending state → preserve resume substrate.
            ("pending", True, "preserve"),
            ("running", True, "preserve"),  # orphans_reset path will own this
            # Has commits + terminal state → salvage.
            ("failed", True, "salvage"),
            ("completed", True, "salvage"),  # v0.5.35 bug class
            (None, True, "salvage"),  # orphan from prior session
        ],
    )
    def test_decide_action_matrix(
        self, task_status: str | None, has_commits: bool, expected: str,
    ) -> None:
        assert decide_action(task_status, has_commits) == expected


class TestSmartCleanupWorktrees:
    def test_no_worktrees_directory_is_a_safe_noop(
        self, git_repo: Path,
    ) -> None:
        outcomes = smart_cleanup_worktrees(git_repo, [])
        assert outcomes == []

    def test_pending_task_with_commits_is_preserved(
        self, git_repo: Path,
    ) -> None:
        """Resume substrate for prefer_resumable — must not be salvaged."""
        # The slug ``alpha-task`` matches make_branch_name's output for this
        # description+category pair; the task fixture is built in lockstep.
        _, wt = _make_worktree_with_commit(git_repo, "alpha-task")
        outcomes = smart_cleanup_worktrees(
            git_repo,
            [_task(description="task", category="alpha", status="pending")],
        )
        assert len(outcomes) == 1
        assert outcomes[0].action == "preserve"
        assert outcomes[0].success is True
        assert wt.exists()
        assert branch_exists(git_repo, "feat/alpha-task")

    def test_failed_task_with_commits_is_salvaged(
        self, git_repo: Path,
    ) -> None:
        """Terminal failure → salvage the work to target."""
        _, wt = _make_worktree_with_commit(git_repo, "beta-task")
        outcomes = smart_cleanup_worktrees(
            git_repo,
            [_task(description="task", category="beta", status="failed")],
        )
        assert len(outcomes) == 1
        assert outcomes[0].action == "salvage"
        assert outcomes[0].success is True
        assert outcomes[0].commit_hash
        assert not wt.exists()
        assert not branch_exists(git_repo, "feat/beta-task")
        # Salvaged work landed on main.
        assert (git_repo / "beta-task.py").exists()

    def test_completed_task_with_commits_is_salvaged(
        self, git_repo: Path,
    ) -> None:
        """v0.5.35 bug class: task says completed but worktree still exists
        because the squash itself failed previously.  Smart mode should pick
        this up and finish what the original squash couldn't.
        """
        _, wt = _make_worktree_with_commit(git_repo, "gamma-task")
        outcomes = smart_cleanup_worktrees(
            git_repo,
            [_task(description="task", category="gamma", status="completed")],
        )
        assert len(outcomes) == 1
        assert outcomes[0].action == "salvage"
        assert outcomes[0].success is True
        assert not wt.exists()

    def test_orphan_with_no_matching_task_is_salvaged(
        self, git_repo: Path,
    ) -> None:
        """No task in the current session owns this slug → orphan from prior
        session.  Salvage it; otherwise it would persist forever.
        """
        _, wt = _make_worktree_with_commit(git_repo, "delta-task")
        outcomes = smart_cleanup_worktrees(git_repo, [])  # no tasks
        assert len(outcomes) == 1
        assert outcomes[0].action == "salvage"
        assert outcomes[0].success is True
        assert not wt.exists()

    def test_empty_branch_is_removed(self, git_repo: Path) -> None:
        """Worktree with no commits ahead of target → just remove the dir."""
        _, wt = create_worktree(git_repo, "task-empty", "empty-task")
        outcomes = smart_cleanup_worktrees(
            git_repo,
            [_task(description="task", category="empty", status="pending")],
        )
        assert len(outcomes) == 1
        assert outcomes[0].action == "remove"
        assert outcomes[0].success is True
        assert not wt.exists()
        # Empty branch removed too.
        assert not branch_exists(git_repo, "feat/empty-task")

    def test_advisor_invoked_on_salvage_conflict(
        self, git_repo: Path,
    ) -> None:
        """When salvage hits a real merge conflict, the advisor is called and
        its returned proposal path is recorded on the outcome.
        """
        # Set up: feature branch and main both modify README.md → conflict.
        _, wt = create_worktree(git_repo, "task-conflict", "conflict-task")
        (wt / "README.md").write_text("# from feature branch\n")
        commit_checkpoint(
            wt, message="readme on feature",
            task_id="task-conflict", plugin="coding", phase="coding",
            session_id="s1",
        )
        (git_repo / "README.md").write_text("# from main\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "main change"],
            cwd=git_repo, check=True,
        )

        captured: dict[str, object] = {}

        def advisor(
            project_dir: Path,
            worktree_path: Path,
            branch: str,
            target: str,
            task: dict[str, object] | None,
        ) -> Path | None:
            captured["called"] = True
            captured["branch"] = branch
            captured["target"] = target
            captured["task_status"] = (task or {}).get("status")
            proposal = worktree_path / "CONFLICT_PROPOSAL.md"
            proposal.write_text("# fake proposal")
            return proposal

        outcomes = smart_cleanup_worktrees(
            git_repo,
            [_task(description="task", category="conflict", status="failed")],
            advisor=advisor,
        )
        assert len(outcomes) == 1
        out = outcomes[0]
        assert out.action == "salvage"
        assert out.success is False  # squash conflict
        assert captured.get("called") is True
        assert captured.get("branch") == "feat/conflict-task"
        assert captured.get("task_status") == "failed"
        assert out.proposal_path is not None
        assert Path(out.proposal_path).read_text() == "# fake proposal"

    def test_advisor_failure_does_not_break_cleanup(
        self, git_repo: Path,
    ) -> None:
        """If the advisor itself raises, the cleanup loop must continue and
        the conflicted worktree is still preserved (the advisor is best-effort).
        """
        _, wt = create_worktree(git_repo, "task-conflict2", "conflict2-task")
        (wt / "README.md").write_text("# branch\n")
        commit_checkpoint(
            wt, message="branch readme",
            task_id="task-conflict2", plugin="coding", phase="coding",
            session_id="s1",
        )
        (git_repo / "README.md").write_text("# main\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "main"], cwd=git_repo, check=True,
        )

        def broken_advisor(*args: object, **kwargs: object) -> Path | None:
            raise RuntimeError("boom")

        # Adding a second non-conflicting worktree to confirm the loop keeps
        # going past the broken-advisor invocation.
        _make_worktree_with_commit(git_repo, "epsilon-task")

        outcomes = smart_cleanup_worktrees(
            git_repo,
            [
                _task(
                    description="task", category="conflict2",
                    status="failed",
                ),
                _task(
                    description="task", category="epsilon", status="failed",
                ),
            ],
            advisor=broken_advisor,
        )
        assert len(outcomes) == 2
        # Conflict worktree preserved with no proposal (advisor crashed).
        conflict = next(o for o in outcomes if "conflict2" in o.branch)
        assert conflict.success is False
        assert conflict.proposal_path is None
        # Non-conflicting one still salvaged successfully.
        clean = next(o for o in outcomes if "epsilon" in o.branch)
        assert clean.success is True


class TestCleanupOutcomeShape:
    def test_outcome_dataclass_fields(self) -> None:
        """Just a sanity check that the dataclass exposes what the renderer
        in cli.py reads.  If a field rename slips through, the renderer
        breaks silently in production startup but this test fails fast.
        """
        out = CleanupOutcome(
            slug="x", branch="feat/x", action="salvage", task_status="failed",
        )
        assert out.success is False
        assert out.commit_hash is None
        assert out.error is None
        assert out.proposal_path is None
        assert out.conflicts == []
