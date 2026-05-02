"""Tests for claw_forge.git.merge — squash-merge feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    create_worktree,
    current_branch,
)
from claw_forge.git.commits import commit_checkpoint
from claw_forge.git.merge import squash_merge, sync_worktree_with_target


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


class TestSquashMerge:
    def test_squash_merge_creates_single_commit(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t1", "auth")
        (git_repo / "auth.py").write_text("login = True\n")
        commit_checkpoint(
            git_repo, message="feat(auth): add login",
            task_id="t1", plugin="coding", phase="milestone", session_id="s1",
        )
        (git_repo / "auth_test.py").write_text("assert True\n")
        commit_checkpoint(
            git_repo, message="test(auth): add test",
            task_id="t1", plugin="testing", phase="milestone", session_id="s1",
        )

        result = squash_merge(git_repo, "feat/auth")
        assert result["merged"] is True
        assert result["commit_hash"]
        assert current_branch(git_repo) in ("main", "master")

    def test_squash_merge_deletes_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t2", "payments")
        (git_repo / "pay.py").write_text("pay = True\n")
        commit_checkpoint(
            git_repo, message="feat(pay): add payments",
            task_id="t2", plugin="coding", phase="milestone", session_id="s1",
        )
        squash_merge(git_repo, "feat/payments")
        assert branch_exists(git_repo, "feat/payments") is False

    def test_squash_merge_custom_target(self, git_repo: Path) -> None:
        # Create a develop branch
        subprocess.run(
            ["git", "checkout", "-b", "develop"],
            cwd=git_repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        create_feature_branch(git_repo, "t3", "nav")
        (git_repo / "nav.py").write_text("nav = True\n")
        commit_checkpoint(
            git_repo, message="feat(nav): add nav",
            task_id="t3", plugin="coding", phase="milestone", session_id="s1",
        )
        result = squash_merge(git_repo, "feat/nav", target="develop")
        assert result["merged"] is True
        assert current_branch(git_repo) == "develop"

    def test_squash_merge_nonexistent_branch(self, git_repo: Path) -> None:
        result = squash_merge(git_repo, "feat/nonexistent")
        assert result["merged"] is False

    def test_squash_merge_with_semantic_message(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "t4", "user-auth")
        (git_repo / "auth.py").write_text("login = True\n")
        commit_checkpoint(
            git_repo, message="Implement login endpoint",
            task_id="t4", plugin="coding", phase="coding", session_id="s1",
        )
        (git_repo / "test_auth.py").write_text("assert True\n")
        commit_checkpoint(
            git_repo, message="Add auth integration tests",
            task_id="t4", plugin="testing", phase="testing", session_id="s1",
        )

        result = squash_merge(
            git_repo, "feat/user-auth",
            title="Implement user authentication",
            steps=["Create login endpoint", "Write integration tests"],
            task_id="t4",
            session_id="s1",
        )
        assert result["merged"] is True

        # Verify the commit message on main
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        body = log.stdout
        assert "Implement user authentication" in body
        assert "Completed Steps:" in body
        assert "- [x] Create login endpoint" in body
        assert "- [x] Write integration tests" in body
        assert "Completed Phases:" in body
        assert "- Implement login endpoint" in body
        assert "- Add auth integration tests" in body
        assert "Task-ID: t4" in body
        assert "Session: s1" in body

    def test_squash_merge_without_context_uses_default(
        self, git_repo: Path,
    ) -> None:
        create_feature_branch(git_repo, "t5", "legacy")
        (git_repo / "legacy.py").write_text("old = True\n")
        commit_checkpoint(
            git_repo, message="feat(legacy): add old module",
            task_id="t5", plugin="coding", phase="coding", session_id="s1",
        )
        squash_merge(git_repo, "feat/legacy")

        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        assert log.stdout.strip() == "merge: feat/legacy (squash)"

    def test_squash_merge_title_no_phases(self, git_repo: Path) -> None:
        """Merge with title but branch has same commits as main (empty phases)."""
        # Create a branch, add a file, but the branch_commit_subjects will
        # return the commit subject. To get empty phases, we need the branch
        # to exist but with no commits ahead of target. Since squash_merge
        # collects phases before merging, we simulate by providing title + steps
        # but the branch has a single commit. The phases list will be non-empty
        # so let's test the no-steps no-phases path instead.
        create_feature_branch(git_repo, "t-np", "no-phases")
        (git_repo / "np.py").write_text("np = True\n")
        commit_checkpoint(
            git_repo, message="only commit",
            task_id="t-np", plugin="coding", phase="coding", session_id="s1",
        )
        # Merge with title but without steps (steps=None)
        result = squash_merge(
            git_repo, "feat/no-phases",
            title="No steps merge",
            task_id="t-np",
        )
        assert result["merged"] is True

    def test_squash_merge_with_title_no_trailers(self, git_repo: Path) -> None:
        """Merge with title but no task_id/session_id — covers branch miss."""
        create_feature_branch(git_repo, "t8", "no-trailers")
        (git_repo / "nt.py").write_text("nt = True\n")
        commit_checkpoint(
            git_repo, message="add nt",
            task_id="t8", plugin="coding", phase="coding", session_id="s1",
        )
        result = squash_merge(
            git_repo, "feat/no-trailers",
            title="Title only merge",
            # no task_id, no session_id, no steps
        )
        assert result["merged"] is True
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        body = log.stdout
        assert "Title only merge" in body
        assert "Task-ID" not in body
        assert "Session" not in body

    def test_squash_merge_conflict_aborts(self, git_repo: Path) -> None:
        """Conflicting merge triggers abort and error return."""
        create_feature_branch(git_repo, "t9", "conflict")
        (git_repo / "README.md").write_text("# conflict branch\n")
        commit_checkpoint(
            git_repo, message="change readme on branch",
            task_id="t9", plugin="coding", phase="coding", session_id="s1",
        )
        # Go back to main and make a conflicting change
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        (git_repo / "README.md").write_text("# main branch conflict\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "conflict on main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        result = squash_merge(git_repo, "feat/conflict")
        assert result["merged"] is False
        assert "error" in result

    def test_squash_merge_with_worktree_cleanup(self, git_repo: Path) -> None:
        branch, wt_path = create_worktree(git_repo, "t6", "wt-merge")
        (wt_path / "wt_file.py").write_text("wt = True\n")
        commit_checkpoint(
            wt_path, message="add wt file",
            task_id="t6", plugin="coding", phase="coding", session_id="s1",
        )

        result = squash_merge(
            git_repo, branch,
            title="Worktree merge",
            task_id="t6",
            worktree_path=wt_path,
        )
        assert result["merged"] is True
        assert not wt_path.exists()
        assert (git_repo / "wt_file.py").exists()

    def test_squash_merge_failure_preserves_worktree(self, git_repo: Path) -> None:
        _, wt_path = create_worktree(git_repo, "t7", "fail-merge")
        # Don't commit anything — merge of empty branch will fail or produce
        # nothing different from main. Use a nonexistent branch to test the
        # failure path where worktree_path is passed but branch is missing.
        result = squash_merge(
            git_repo, "nonexistent/branch",
            worktree_path=wt_path,
        )
        assert result["merged"] is False
        # Worktree should still exist since merge failed
        assert wt_path.exists()

    def test_squash_merge_no_op_when_branch_already_merged(
        self, git_repo: Path,
    ) -> None:
        """When the feature branch's content is already fully reachable from
        target (e.g. another concurrent task squashed identical content
        first), ``git merge --squash`` succeeds with no staged changes and
        the subsequent ``git commit --no-verify -m msg`` would fail with
        ``nothing to commit``.  squash_merge must detect this and return a
        no-op success rather than a phantom 'Merge failed'.
        """
        branch, wt_path = create_worktree(git_repo, "t-noop", "noop")
        # Worktree branched from main with no new commits — merge --squash
        # will succeed but stage zero changes.
        result = squash_merge(
            git_repo, branch,
            title="No-op merge",
            task_id="t-noop",
            worktree_path=wt_path,
        )
        assert result["merged"] is True, (
            f"Expected no-op success, got: {result!r}"
        )
        # Worktree + branch should be cleaned up just like a regular merge.
        assert not wt_path.exists()
        assert branch_exists(git_repo, branch) is False

    def test_squash_merge_sidelines_untracked_orphan_blocking_merge(
        self, git_repo: Path,
    ) -> None:
        """When project_dir's working tree has an untracked file at the same
        path that a feat branch is adding, ``git merge --squash`` aborts
        with "untracked working tree files would be overwritten" (exit 1).
        squash_merge must detect this case, sideline the orphan to
        ``.claw-forge/orphans/<timestamp>/`` (preserving it for recovery),
        and retry — at which point the merge succeeds.
        """
        branch, wt_path = create_worktree(git_repo, "t-orphan", "orphan")
        (wt_path / "new_file.py").write_text("def new():\n    pass\n")
        commit_checkpoint(
            wt_path, message="add new_file.py",
            task_id="t-orphan", plugin="coding", phase="coding", session_id="s1",
        )
        # Plant an orphan with the same relative path in project_dir's working
        # tree (debris from a previous failed run, in production).
        orphan_content = "# orphan from a previous failed run\n"
        (git_repo / "new_file.py").write_text(orphan_content)

        result = squash_merge(git_repo, branch, worktree_path=wt_path)
        assert result["merged"] is True, result
        # Branch's new content lands in main.
        assert (git_repo / "new_file.py").read_text() == "def new():\n    pass\n"
        # Orphan preserved in the archive so the user can recover it if needed.
        archive_root = git_repo / ".claw-forge" / "orphans"
        assert archive_root.exists(), "orphans archive directory not created"
        archived = list(archive_root.rglob("new_file.py"))
        assert len(archived) == 1, f"expected 1 archived orphan, got {archived!r}"
        assert archived[0].read_text() == orphan_content

    def test_squash_merge_sidelines_multiple_orphan_files(
        self, git_repo: Path,
    ) -> None:
        """Multiple orphans blocking the same merge are all sidelined."""
        branch, wt_path = create_worktree(git_repo, "t-multi", "multi-orphan")
        (wt_path / "a.py").write_text("a = 1\n")
        (wt_path / "b.py").write_text("b = 2\n")
        commit_checkpoint(
            wt_path, message="add a.py and b.py",
            task_id="t-multi", plugin="coding", phase="coding", session_id="s1",
        )
        (git_repo / "a.py").write_text("# orphan a\n")
        (git_repo / "b.py").write_text("# orphan b\n")

        result = squash_merge(git_repo, branch, worktree_path=wt_path)
        assert result["merged"] is True, result
        archive_root = git_repo / ".claw-forge" / "orphans"
        assert len(list(archive_root.rglob("a.py"))) == 1
        assert len(list(archive_root.rglob("b.py"))) == 1

    def test_squash_merge_recovery_does_not_checkout_worktree_branch(
        self, git_repo: Path,
    ) -> None:
        """Regression: when squash merge falls into the conflict-recovery path,
        it must NOT try to ``git checkout <branch>`` from project_dir — that
        branch is already checked out in the worktree, so the checkout fails
        with ``fatal: '<branch>' is already used by worktree at ...`` (exit
        128).  The recovery must operate inside the worktree where the branch
        is checked out.
        """
        branch, wt_path = create_worktree(git_repo, "t-rec", "rec")
        (wt_path / "README.md").write_text("# from feature branch\n")
        commit_checkpoint(
            wt_path, message="readme change on feature",
            task_id="t-rec", plugin="coding", phase="coding", session_id="s1",
        )

        # Conflicting change on main — forces ``git merge --squash`` to fail
        # which triggers the recovery path.
        (git_repo / "README.md").write_text("# from main\n")
        subprocess.run(
            ["git", "add", "."], cwd=git_repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "readme change on main"],
            cwd=git_repo, check=True, capture_output=True,
        )

        result = squash_merge(git_repo, branch, worktree_path=wt_path)

        # Even if the merge ultimately fails (true content conflict), the error
        # must NOT be the bogus "checkout already-held branch" failure.
        err = result.get("error", "")
        assert "'checkout', 'feat/" not in err, (
            "Recovery path tried to `git checkout` a worktree-held branch "
            f"from project_dir — error: {err!r}"
        )

    def test_squash_merge_invokes_catchup_rebase_on_conflict(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression for the exception-handler ordering bug: when
        ``git merge --squash`` raises ``CalledProcessError``, the catch-up
        rebase (``b0d0908`` + ``75baa2a``) MUST be attempted inside the
        worktree.  The orphan-sideline fix (``84d6b72``) used a sibling
        ``except subprocess.CalledProcessError`` clause, and because that's a
        subclass of ``Exception``, the first-match-wins rule made the
        catch-up clause unreachable for any non-orphan failure — so every
        post-merge-divergence squash returned a phantom 'Merge failed'
        instead of recovering.

        This test patches ``_run_git`` to record every git invocation, then
        triggers a real conflict.  The recovery sequence — ``reset --hard
        HEAD`` in project_dir, ``merge --no-verify --no-edit <target>``
        inside the worktree, and a retry ``merge --squash`` — must all show
        up.  An assertion on the orphan path alone (or on the absence of a
        bogus ``checkout``) would let the regression slip through again.
        """
        from claw_forge.git import merge as merge_module

        branch, wt_path = create_worktree(git_repo, "t-cu", "catchup")
        (wt_path / "README.md").write_text("# from feature branch\n")
        commit_checkpoint(
            wt_path, message="readme on feature",
            task_id="t-cu", plugin="coding", phase="coding", session_id="s1",
        )
        (git_repo / "README.md").write_text("# from main\n")
        subprocess.run(
            ["git", "add", "."], cwd=git_repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "main change"],
            cwd=git_repo, check=True, capture_output=True,
        )

        invocations: list[tuple[tuple[str, ...], Path]] = []
        real_run_git = merge_module._run_git

        def tracking_run_git(args: list[str], cwd: Path):  # type: ignore[no-untyped-def]
            invocations.append((tuple(args), cwd))
            return real_run_git(args, cwd)

        monkeypatch.setattr(merge_module, "_run_git", tracking_run_git)

        squash_merge(git_repo, branch, worktree_path=wt_path)

        catchup_in_worktree = [
            (args, cwd) for (args, cwd) in invocations
            if cwd == wt_path
            and args[:1] == ("merge",)
            and "--no-edit" in args
            and "--squash" not in args
        ]
        assert catchup_in_worktree, (
            "catch-up rebase (`git merge --no-verify --no-edit <target>` "
            "inside the worktree) was never invoked — the catch-up handler "
            "is unreachable. Recorded invocations:\n  "
            + "\n  ".join(f"{a} (cwd={c})" for (a, c) in invocations)
        )


@pytest.fixture()
def repo_with_worktree(tmp_path: Path) -> tuple[Path, Path, str]:
    """Build a repo with a feature branch in its own worktree.

    Returns (project_dir, worktree_path, branch_name).
    The branch is forked from main but does NOT yet have any unique commits.
    """
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project, check=True, capture_output=True,
    )
    (project / "a.py").write_text("v0\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=project, check=True, capture_output=True,
    )

    wt = tmp_path / "worktrees" / "feat-x"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/x", str(wt)],
        cwd=project, check=True, capture_output=True,
    )
    return project, wt, "feat/x"


def _commit_in(repo: Path, name: str, content: str, msg: str) -> None:
    (repo / name).write_text(content)
    subprocess.run(
        ["git", "add", name], cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, check=True, capture_output=True,
    )


class TestSyncWorktreeWithTarget:
    def test_no_op_when_already_up_to_date(
        self, repo_with_worktree: tuple[Path, Path, str],
    ) -> None:
        project, wt, _branch = repo_with_worktree
        result = sync_worktree_with_target(project, wt, target="main")
        assert result == {"synced": True, "no_op": True, "merged_count": 0}

    def test_clean_merge_pulls_target_commits(
        self, repo_with_worktree: tuple[Path, Path, str],
    ) -> None:
        project, wt, _branch = repo_with_worktree
        # Branch edits a different file than main will edit.
        _commit_in(wt, "branch_only.py", "x\n", "branch work")
        # Main moves on a different file — no overlap.
        _commit_in(project, "main_only.py", "y\n", "main work")
        result = sync_worktree_with_target(project, wt, target="main")
        assert result["synced"] is True
        assert result.get("no_op") is not True
        assert result["merged_count"] == 1
        # Target's file should now exist in the worktree.
        assert (wt / "main_only.py").exists()

    def test_conflict_returns_files_and_aborts(
        self, repo_with_worktree: tuple[Path, Path, str],
    ) -> None:
        project, wt, _branch = repo_with_worktree
        # Both sides change a.py incompatibly.
        _commit_in(wt, "a.py", "branch-version\n", "branch edits a")
        _commit_in(project, "a.py", "main-version\n", "main edits a")
        result = sync_worktree_with_target(project, wt, target="main")
        assert result["synced"] is False
        assert result["conflicts"] == ["a.py"]
        # Worktree must be clean after abort — not in a half-merged state.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=wt, check=True, capture_output=True, text=True,
        ).stdout.strip()
        assert status == ""
        # And the branch tip should still be the agent's commit, not a half-merge.
        head_subject = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=wt, check=True, capture_output=True, text=True,
        ).stdout.strip()
        assert head_subject == "branch edits a"

    def test_refuses_when_worktree_has_uncommitted_changes(
        self, repo_with_worktree: tuple[Path, Path, str],
    ) -> None:
        project, wt, _branch = repo_with_worktree
        (wt / "uncommitted.py").write_text("dirty\n")
        # Force a target commit so a real merge would otherwise be needed.
        _commit_in(project, "main_only.py", "y\n", "main work")
        result = sync_worktree_with_target(project, wt, target="main")
        assert result["synced"] is False
        assert result.get("dirty_worktree") is True
        # The dirty file is preserved.
        assert (wt / "uncommitted.py").read_text() == "dirty\n"
