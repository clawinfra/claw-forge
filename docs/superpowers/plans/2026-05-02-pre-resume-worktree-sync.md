# Pre-Resume Worktree Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that `claw-forge run` with a single agent never produces the merge-conflict failure pattern (`Merge failed for feat/<slug>: Command '['git', 'merge', '--no-verify', '--no-edit', 'main']' returned non-zero exit status 1`). Today, the catch-up rebase in `squash_merge` is the *first* time a resumed branch sees `main`'s newer commits — by then the agent has already wasted its turn on stale state. This plan moves the catch-up to **dispatch time** so any conflict is surfaced up front and the agent only ever runs against a synchronised worktree.

**Architecture:** Three new units inside `claw_forge/git/` plus a dispatcher hook:

1. `branch_overlap_files()` — pure helper in `branching.py`. Returns the list of paths modified on both `branch` and `target` since their merge-base. Used for human-readable diagnostics in the conflict report and as a unit-testable building block; not used as a gate.
2. `sync_worktree_with_target()` — new function in `merge.py`. Runs `git merge --no-verify --no-edit <target>` inside the worktree. Returns a structured result: clean / no-op / conflict-with-file-list. On conflict it always restores the worktree to a clean state via `git merge --abort`.
3. `GitOps.sync_worktree()` — thin async wrapper in `claw_forge/git/__init__.py`.
4. **Dispatcher integration** in `cli.py`: after `create_worktree` returns, call `sync_worktree` unconditionally. On conflict, mark the task `failed` with a structured `error_message` and skip the agent dispatch. The existing worktree-preservation behaviour means the user can `cd` into the worktree, resolve manually, and requeue.

The existing catch-up rebase inside `squash_merge` stays — it still protects against `main` moving *during* agent execution (multi-agent case). The new sync covers the *between-runs / before-execution* gap.

**Tech Stack:** Python 3.11+, subprocess to git CLI, pytest with `tmp_path` git-repo fixtures. No new dependencies. No DB schema changes (we reuse the existing `error_message` text column on tasks).

**Single-agent invariant proven:** with this change, in a one-task-at-a-time `claw-forge run`, every worktree handed to an agent is either (a) freshly forked from current `main` HEAD (no drift possible) or (b) a resumed branch that has just been merged with current `main` (drift resolved before the agent sees it). The agent's commits therefore can never produce a `git merge --squash` conflict on overlapping files at completion. Multi-agent runs retain their existing protections (file-claims + catch-up rebase in `squash_merge`).

---

## File Structure

| File | Role | Action |
|---|---|---|
| `claw_forge/git/branching.py` | Branch / worktree primitives | Modify — add `branch_overlap_files()` |
| `claw_forge/git/merge.py` | Squash-merge logic | Modify — add `sync_worktree_with_target()` |
| `claw_forge/git/__init__.py` | `GitOps` async facade | Modify — add `sync_worktree()` method |
| `claw_forge/cli.py` | Dispatcher startup + task handler | Modify — call `sync_worktree` after `create_worktree` |
| `tests/git/test_branching.py` | Branching unit tests | Modify — tests for `branch_overlap_files` |
| `tests/git/test_merge.py` | Merge unit tests | Modify — tests for `sync_worktree_with_target` |
| `tests/git/test_dispatcher_git.py` | Dispatcher integration tests | Modify — resume-with-conflict scenario |
| `CLAUDE.md` | Architecture docs | Modify — document the sync invariant |
| `docs/commands.md` | User-facing CLI docs | Modify — note the new resume-conflict failure mode |
| `README.md` | High-level project docs | Modify — update "How a `claw-forge run` works" if it lists ordering |

---

## Phase 1: `branch_overlap_files` Helper

### Task 1: Add `branch_overlap_files` to `branching.py`

**Files:**
- Modify: `claw_forge/git/branching.py` (append after `branch_age_in_commits`, around line 56)
- Test: `tests/git/test_branching.py` (append new test class)

- [ ] **Step 1: Write failing tests for `branch_overlap_files`**

Add to `tests/git/test_branching.py`:

```python
import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import branch_overlap_files


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    (repo / name).write_text(content)
    subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, check=True, capture_output=True,
    )


class TestBranchOverlapFiles:
    def test_returns_empty_when_branch_at_target(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        assert branch_overlap_files(git_repo, "feat/x", "main") == []

    def test_returns_empty_when_no_file_overlap(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "branch_only.txt", "branch", "branch change")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "main_only.txt", "main", "main change")
        assert branch_overlap_files(git_repo, "feat/x", "main") == []

    def test_returns_overlapping_files_sorted(self, git_repo: Path) -> None:
        _commit_file(git_repo, "a.py", "v0", "seed a")
        _commit_file(git_repo, "b.py", "v0", "seed b")
        subprocess.run(
            ["git", "checkout", "-b", "feat/x"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "b.py", "branch", "branch edits b")
        _commit_file(git_repo, "a.py", "branch", "branch edits a")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=git_repo, check=True, capture_output=True,
        )
        _commit_file(git_repo, "a.py", "main", "main edits a")
        _commit_file(git_repo, "b.py", "main", "main edits b")
        # Both sides touched a.py and b.py since the merge-base
        assert branch_overlap_files(git_repo, "feat/x", "main") == ["a.py", "b.py"]

    def test_returns_empty_for_unknown_branch(self, git_repo: Path) -> None:
        assert branch_overlap_files(git_repo, "feat/missing", "main") == []
```

- [ ] **Step 2: Run tests — confirm they fail with `ImportError`**

Run: `uv run pytest tests/git/test_branching.py::TestBranchOverlapFiles -v`
Expected: All four tests fail with `ImportError: cannot import name 'branch_overlap_files'`.

- [ ] **Step 3: Implement `branch_overlap_files`**

Append to `claw_forge/git/branching.py` immediately after `branch_age_in_commits` (~line 56):

```python
def branch_overlap_files(
    project_dir: Path, branch: str, base: str = "main",
) -> list[str]:
    """Return files modified on both *branch* and *base* since their merge-base.

    Used as a diagnostic signal for "this resume is going to conflict": if the
    list is non-empty, ``git merge base`` from inside *branch* is at risk of
    failing on overlapping changes.  Pure read; nothing is mutated.

    Returns ``[]`` when the branch does not exist, when there is no merge-base,
    or when neither side has touched any common file.  Result is sorted.
    """
    try:
        merge_base = _run_git(
            ["merge-base", base, branch], project_dir,
        ).stdout.strip()
    except Exception:
        return []
    if not merge_base:
        return []
    try:
        target_changed = set(
            _run_git(
                ["diff", "--name-only", merge_base, base], project_dir,
            ).stdout.splitlines()
        )
        branch_changed = set(
            _run_git(
                ["diff", "--name-only", merge_base, branch], project_dir,
            ).stdout.splitlines()
        )
    except Exception:
        return []
    return sorted(target_changed & branch_changed)
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `uv run pytest tests/git/test_branching.py::TestBranchOverlapFiles -v`
Expected: 4 passed.

- [ ] **Step 5: Run full git test suite to confirm nothing regressed**

Run: `uv run pytest tests/git/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/git/branching.py tests/git/test_branching.py
git commit -m "feat(git): add branch_overlap_files diagnostic helper"
```

---

## Phase 2: `sync_worktree_with_target` Function

### Task 2: Add `sync_worktree_with_target` to `merge.py`

**Files:**
- Modify: `claw_forge/git/merge.py` (new function near top, before `squash_merge`)
- Test: `tests/git/test_merge.py` (append new test class)

- [ ] **Step 1: Write failing tests for `sync_worktree_with_target`**

Append to `tests/git/test_merge.py` (or insert into an existing fixture file using the same `git_repo` setup conventions):

```python
import subprocess
from pathlib import Path

import pytest

from claw_forge.git.merge import sync_worktree_with_target


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
```

- [ ] **Step 2: Run tests — confirm they fail with `ImportError`**

Run: `uv run pytest tests/git/test_merge.py::TestSyncWorktreeWithTarget -v`
Expected: All four tests fail with `ImportError: cannot import name 'sync_worktree_with_target'`.

- [ ] **Step 3: Implement `sync_worktree_with_target`**

Add to `claw_forge/git/merge.py` immediately after the `_sideline_orphans` helper (~line 84) and before `_build_merge_message`:

```python
def sync_worktree_with_target(
    project_dir: Path,
    worktree_path: Path,
    target: str = "main",
) -> dict[str, Any]:
    """Bring the branch checked out in *worktree_path* up to date with *target*.

    Runs ``git merge --no-verify --no-edit <target>`` inside the worktree.
    Three outcomes are possible:

    - **No-op**: ``target`` is already an ancestor of the branch.  Return
      ``{"synced": True, "no_op": True, "merged_count": 0}``.
    - **Clean merge**: ``target`` had unseen commits and they merged
      without conflict.  Return ``{"synced": True, "merged_count": N}``.
    - **Conflict**: overlapping changes on one or more files.  The merge
      is aborted (``git merge --abort``) so the worktree is left in the
      same state it had before the call.  Return
      ``{"synced": False, "conflicts": [...]}``.

    A precondition: the worktree must have no uncommitted changes.  If
    it does, return ``{"synced": False, "dirty_worktree": True}`` and do
    nothing — merging on top of dirty state risks losing the user's edits.
    Callers that want to dispatch an agent into this worktree should treat
    that as a hard failure, same as a conflict.
    """
    # Refuse on dirty worktree — never overwrite uncommitted edits.
    status = _run_git(
        ["status", "--porcelain"], worktree_path,
    ).stdout.strip()
    if status:
        return {"synced": False, "dirty_worktree": True}

    # Count how many target commits are unseen by the branch.  If zero,
    # the merge will be a no-op.
    behind_count = 0
    try:
        behind_count = int(
            _run_git(
                ["rev-list", "--count", f"HEAD..{target}"], worktree_path,
            ).stdout.strip()
        )
    except Exception:
        # If we can't measure, fall through to attempting the merge anyway.
        behind_count = 0

    if behind_count == 0:
        return {"synced": True, "no_op": True, "merged_count": 0}

    try:
        _run_git(
            ["merge", "--no-verify", "--no-edit", target], worktree_path,
        )
        return {"synced": True, "merged_count": behind_count}
    except subprocess.CalledProcessError:
        # Conflict — collect the conflicted paths from the index, then abort.
        conflicts: list[str] = []
        try:
            conflicts = sorted(
                set(
                    _run_git(
                        ["diff", "--name-only", "--diff-filter=U"], worktree_path,
                    ).stdout.splitlines()
                )
            )
        except Exception:
            conflicts = []
        with suppress(Exception):
            _run_git(["merge", "--abort"], worktree_path)
        with suppress(Exception):
            _run_git(["reset", "--hard", "HEAD"], worktree_path)
        return {"synced": False, "conflicts": conflicts}
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `uv run pytest tests/git/test_merge.py::TestSyncWorktreeWithTarget -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full merge test file to confirm no regression**

Run: `uv run pytest tests/git/test_merge.py -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/git/merge.py tests/git/test_merge.py
git commit -m "feat(git): sync_worktree_with_target — pre-dispatch catch-up merge"
```

---

## Phase 3: `GitOps` Async Wrapper

### Task 3: Add `GitOps.sync_worktree` method

**Files:**
- Modify: `claw_forge/git/__init__.py` (new method around line 116, after `remove_worktree`)
- Test: `tests/git/test_git_init.py` (or wherever `GitOps` is tested) — add test

- [ ] **Step 1: Write failing test for `GitOps.sync_worktree`**

Find or create the test file for `GitOps`. Inspect with:

Run: `grep -rn "class TestGitOps\|def test_.*git_ops\|GitOps(" tests/git/ | head -10`

Append a test class (use the existing `git_repo` fixture pattern). Place it in the file that already exercises `GitOps` — likely `tests/git/test_git_init.py`:

```python
import asyncio
import subprocess
from pathlib import Path

import pytest

from claw_forge.git import GitOps


class TestGitOpsSyncWorktree:
    def test_disabled_returns_none(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=False)
        result = asyncio.run(ops.sync_worktree(git_repo, target="main"))
        assert result is None

    def test_enabled_no_op(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        subprocess.run(
            ["git", "worktree", "add", "-b", "feat/x", str(wt)],
            cwd=git_repo, check=True, capture_output=True,
        )
        ops = GitOps(project_dir=git_repo, enabled=True)
        result = asyncio.run(ops.sync_worktree(wt, target="main"))
        assert result == {"synced": True, "no_op": True, "merged_count": 0}
```

- [ ] **Step 2: Run test — confirm it fails with `AttributeError`**

Run: `uv run pytest tests/git/test_git_init.py::TestGitOpsSyncWorktree -v`
Expected: fail with `AttributeError: 'GitOps' object has no attribute 'sync_worktree'`.

- [ ] **Step 3: Implement `GitOps.sync_worktree`**

In `claw_forge/git/__init__.py`, find the import block at the top of the file. Add `sync_worktree_with_target` to the import from `claw_forge.git.merge`:

```python
from claw_forge.git.merge import squash_merge, sync_worktree_with_target
```

Then add this method to the `GitOps` class, immediately after `remove_worktree` (around line 116):

```python
async def sync_worktree(
    self,
    worktree_path: Path,
    *,
    target: str = "main",
) -> dict[str, Any] | None:
    """Bring the branch in *worktree_path* up to date with *target*.

    Lock-free: the merge mutates only the worktree's own HEAD/index, not
    the project_dir's working tree.  Returns ``None`` when git is disabled.
    """
    if not self.enabled:
        return None
    return await asyncio.to_thread(
        sync_worktree_with_target, self.project_dir, worktree_path, target,
    )
```

Also add `sync_worktree_with_target` to the `__all__` export list at the bottom of `claw_forge/git/__init__.py` if there is one:

```python
"sync_worktree_with_target",
```

- [ ] **Step 4: Run test — confirm it passes**

Run: `uv run pytest tests/git/test_git_init.py::TestGitOpsSyncWorktree -v`
Expected: 2 passed.

- [ ] **Step 5: Run all git tests**

Run: `uv run pytest tests/git/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/git/__init__.py tests/git/test_git_init.py
git commit -m "feat(git): GitOps.sync_worktree async wrapper"
```

---

## Phase 4: Dispatcher Integration

### Task 4: Wire `sync_worktree` into the task handler

**Files:**
- Modify: `claw_forge/cli.py` (task handler, around lines 1218–1234, immediately after `create_worktree`)
- Test: `tests/git/test_dispatcher_git.py` (new test for the resume-conflict path)

- [ ] **Step 1: Write failing integration test**

Append to `tests/git/test_dispatcher_git.py`. The exact harness to use depends on what `test_dispatcher_git.py` already provides — first inspect:

Run: `grep -n "def test_\|fixture\|async def" tests/git/test_dispatcher_git.py | head -30`

Add a focused test that exercises the new dispatcher behaviour without booting the full state service. The test should:

1. Build a git repo with a feature branch that has both committed work AND a conflict with `main`.
2. Call the helper that wraps `create_worktree + sync_worktree` (introduced in step 3 below as `_create_and_sync_worktree`).
3. Assert that `synced` is False and the returned conflict dict carries the conflicting filenames.

```python
import subprocess
from pathlib import Path

import pytest

from claw_forge.cli import _create_and_sync_worktree
from claw_forge.git import GitOps


@pytest.fixture()
def conflicted_resume_repo(tmp_path: Path) -> tuple[Path, str]:
    """Repo with feat/x carrying committed work that conflicts with main.

    Returns (project_dir, slug).  The slug is what the dispatcher would
    pass to create_worktree.
    """
    project = tmp_path / "proj"
    project.mkdir()
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(cmd, cwd=project, check=True, capture_output=True)
    (project / "shared.py").write_text("v0\n")
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=project, check=True, capture_output=True,
    )

    # Create the feature branch + worktree at the seed commit.
    wt = project / ".claw-forge" / "worktrees" / "x"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/x", str(wt)],
        cwd=project, check=True, capture_output=True,
    )
    # Branch commits its conflicting version of shared.py.
    (wt / "shared.py").write_text("branch-version\n")
    subprocess.run(
        ["git", "add", "shared.py"],
        cwd=wt, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "branch edits shared"],
        cwd=wt, check=True, capture_output=True,
    )
    # Main commits its incompatible version.
    (project / "shared.py").write_text("main-version\n")
    subprocess.run(
        ["git", "add", "shared.py"],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "main edits shared"],
        cwd=project, check=True, capture_output=True,
    )
    return project, "x"


@pytest.mark.asyncio
async def test_create_and_sync_surfaces_resume_conflict(
    conflicted_resume_repo: tuple[Path, str],
) -> None:
    project, slug = conflicted_resume_repo
    ops = GitOps(project_dir=project, enabled=True)
    result = await _create_and_sync_worktree(
        ops, task_id="t1", slug=slug, prefix="feat", target="main",
    )
    assert result is not None
    assert result["worktree_path"] == project / ".claw-forge" / "worktrees" / "x"
    assert result["sync"]["synced"] is False
    assert result["sync"]["conflicts"] == ["shared.py"]


@pytest.mark.asyncio
async def test_create_and_sync_clean_resume(tmp_path: Path) -> None:
    """Resume with no conflict: sync is a clean merge of main into branch."""
    project = tmp_path / "proj"
    project.mkdir()
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(cmd, cwd=project, check=True, capture_output=True)
    (project / "a.py").write_text("v0\n")
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=project, check=True, capture_output=True,
    )

    wt = project / ".claw-forge" / "worktrees" / "y"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/y", str(wt)],
        cwd=project, check=True, capture_output=True,
    )
    (wt / "branch_only.py").write_text("b\n")
    subprocess.run(["git", "add", "."], cwd=wt, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "branch work"],
        cwd=wt, check=True, capture_output=True,
    )
    (project / "main_only.py").write_text("m\n")
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "main work"],
        cwd=project, check=True, capture_output=True,
    )

    ops = GitOps(project_dir=project, enabled=True)
    result = await _create_and_sync_worktree(
        ops, task_id="t1", slug="y", prefix="feat", target="main",
    )
    assert result is not None
    assert result["sync"]["synced"] is True
    assert result["sync"].get("merged_count", 0) >= 1
    # Worktree now has main_only.py from main.
    assert (wt / "main_only.py").exists()
```

- [ ] **Step 2: Run tests — confirm they fail with `ImportError`**

Run: `uv run pytest tests/git/test_dispatcher_git.py::test_create_and_sync_surfaces_resume_conflict tests/git/test_dispatcher_git.py::test_create_and_sync_clean_resume -v`
Expected: fail with `ImportError: cannot import name '_create_and_sync_worktree'`.

- [ ] **Step 3: Extract `_create_and_sync_worktree` helper in `cli.py`**

In `claw_forge/cli.py`, find the imports block and add (next to other `claw_forge.git` imports if there is a grouped block; otherwise at the top of the file):

```python
from claw_forge.git import GitOps
```

Then **above** the `async def main()` definition (e.g. just before the `def _apply_resumable_flag` function around line 295, or alongside other module-level helpers), add:

```python
async def _create_and_sync_worktree(
    git_ops: "GitOps",
    *,
    task_id: str,
    slug: str,
    prefix: str,
    target: str,
) -> dict[str, Any] | None:
    """Create (or resume) a worktree, then synchronise it with *target*.

    Returns ``None`` when git is disabled or worktree creation failed.
    Otherwise returns ``{"branch": str, "worktree_path": Path, "sync": dict}``
    where ``sync`` is the result of ``GitOps.sync_worktree`` — callers should
    inspect ``sync["synced"]`` before dispatching an agent into the worktree.
    """
    wt_result = await git_ops.create_worktree(
        task_id, slug, prefix=prefix, base_branch=target,
    )
    if not wt_result:
        return None
    branch_name, worktree_path = wt_result
    sync_result = await git_ops.sync_worktree(worktree_path, target=target)
    return {
        "branch": branch_name,
        "worktree_path": worktree_path,
        "sync": sync_result or {"synced": True, "no_op": True, "merged_count": 0},
    }
```

- [ ] **Step 4: Run tests — confirm both new tests pass**

Run: `uv run pytest tests/git/test_dispatcher_git.py::test_create_and_sync_surfaces_resume_conflict tests/git/test_dispatcher_git.py::test_create_and_sync_clean_resume -v`
Expected: 2 passed.

- [ ] **Step 5: Commit the helper**

```bash
git add claw_forge/cli.py tests/git/test_dispatcher_git.py
git commit -m "feat(cli): _create_and_sync_worktree helper for pre-dispatch sync"
```

### Task 5: Use the helper in the task handler & surface conflicts to the state service

**Files:**
- Modify: `claw_forge/cli.py` (task handler, the `if git_enabled: try: _wt_result = await git_ops.create_worktree(...)` block at lines 1218–1234)

- [ ] **Step 1: Replace the `create_worktree` call with `_create_and_sync_worktree`**

In `claw_forge/cli.py`, find the block (around line 1218):

```python
_worktree_path: Path | None = None
if git_enabled:
    try:
        _wt_result = await git_ops.create_worktree(
            task_node.id,
            _slug,
            prefix=git_branch_prefix,
            base_branch=_default_branch,
        )
        if _wt_result:
            _, _worktree_path = _wt_result
            _active_worktrees[task_node.id] = _worktree_path
    except Exception as _git_wt_err:
        _logging.getLogger(__name__).warning(
            "Git worktree creation failed for task %s (continuing): %s",
            task_node.id, _git_wt_err,
        )
```

Replace it with:

```python
_worktree_path: Path | None = None
if git_enabled:
    try:
        _wt_bundle = await _create_and_sync_worktree(
            git_ops,
            task_id=task_node.id,
            slug=_slug,
            prefix=git_branch_prefix,
            target=_default_branch,
        )
        if _wt_bundle:
            _worktree_path = _wt_bundle["worktree_path"]
            _active_worktrees[task_node.id] = _worktree_path
            _sync = _wt_bundle["sync"]
            if not _sync.get("synced"):
                # Pre-dispatch sync hit a conflict (or dirty worktree).  The
                # agent must NOT run on stale state — surface the conflict
                # as a task failure with the file list, preserve the
                # worktree so the user can resolve manually, and skip
                # agent execution for this dispatch cycle.
                _conflict_files = _sync.get("conflicts", [])
                _dirty = _sync.get("dirty_worktree", False)
                if _dirty:
                    _msg = (
                        f"resume_conflict: worktree has uncommitted changes; "
                        f"resolve in {_worktree_path} (commit or discard) "
                        "before retrying."
                    )
                else:
                    _msg = (
                        "resume_conflict: catch-up merge of "
                        f"{_default_branch} into branch failed on "
                        f"{len(_conflict_files)} file(s): "
                        f"{', '.join(_conflict_files)}. Resolve manually "
                        f"in {_worktree_path} (run `git merge "
                        f"{_default_branch}`, fix conflicts, commit) and "
                        "requeue the task."
                    )
                await _patch_task(
                    http, task_node.id,
                    status="failed",
                    error_message=_msg,
                )
                _logging.getLogger(__name__).warning(
                    "Task %s: %s", task_node.id, _msg,
                )
                # Release any file claims this task was holding.
                with suppress(Exception):
                    await http.delete(
                        f"{_state_base}/sessions/{session_id}"
                        f"/file-claims/{task_node.id}",
                        timeout=5,
                    )
                # Deregister the worktree so the SIGTERM handler doesn't
                # try to commit into a clean worktree later.
                _active_worktrees.pop(task_node.id, None)
                return {"success": False, "output": "resume_conflict"}
    except Exception as _git_wt_err:
        _logging.getLogger(__name__).warning(
            "Git worktree creation failed for task %s (continuing): %s",
            task_node.id, _git_wt_err,
        )
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green. New behaviour is gated by the conflict path; no existing test exercises the resume-with-conflict scenario, so existing tests should be unaffected.

- [ ] **Step 3: Smoke-test manually against the user's stuck repo**

This is a one-off verification, not a permanent test. Build the wheel and exercise it against the real artifact:

```bash
cd /Users/bowenli/development/claw-forge
uv pip install -e .
cd /Users/bowenli/development/agent-trading-arena
claw-forge worktrees list
# Expect: dsl-executor-system-returns-current-price-by-calling-br listed
# Expect: 2-3 commits ahead of main
```

Then trigger a resume of that task:

```bash
claw-forge run --resume <task-id>   # or whatever the resume command is
# Expect: task immediately marked failed with error_message starting "resume_conflict:"
# Expect: error lists shared files (skill/dsl/executor.py, skill/broker/base.py, skill/broker/paper.py)
# Expect: worktree directory still present
```

- [ ] **Step 4: Run lint + type check**

Run: `uv run ruff check claw_forge/ tests/ --fix && uv run mypy claw_forge/ --ignore-missing-imports`
Expected: clean.

- [ ] **Step 5: Run coverage to confirm 90% gate still holds**

Run: `uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing`
Expected: total coverage ≥ 90%.

- [ ] **Step 6: Commit**

```bash
git add claw_forge/cli.py
git commit -m "feat(cli): surface resume conflicts as task failures pre-dispatch"
```

---

## Phase 5: Documentation

### Task 6: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (Architecture Overview block, Key Conventions block)

- [ ] **Step 1: Add `merge.py` line in the Three-Layer Stack**

In `CLAUDE.md`, find the `Git Workspace Tracking` block in the "Three-Layer Stack" section. Update the `claw_forge/git/merge.py` line to mention the sync helper:

```
  claw_forge/git/merge.py    — squash-merge feature branches; sync_worktree_with_target catches up resumed branches before dispatch
```

- [ ] **Step 2: Add a "Pre-Dispatch Worktree Sync" subsection**

In `CLAUDE.md`, find the "Git Worktree Lifecycle" section. Append a new subsection after the existing one (before "Periodic Auto-Checkpoint"):

```markdown
### Pre-Dispatch Worktree Sync (`cli.py` `_create_and_sync_worktree`)

After every `create_worktree` call (fresh or resume), the dispatcher runs `git merge --no-verify --no-edit <target>` inside the worktree via `GitOps.sync_worktree`. Three outcomes:

- **No-op** (target is an ancestor of branch — fresh worktrees): proceeds to agent dispatch.
- **Clean merge** (target moved on non-overlapping files): proceeds to agent dispatch with the worktree updated to include target's new commits.
- **Conflict** (target moved on files the branch also touched): the merge is aborted (`git merge --abort`), the task is PATCHed to `status=failed` with a structured `error_message` of the form `"resume_conflict: catch-up merge of <target> into branch failed on N file(s): a.py, b.py. Resolve manually in <worktree_path> ..."`, file claims are released, and the agent is **never started**.

This eliminates the failure pattern where a resumed task wastes its agent turn writing on top of stale state and only discovers the conflict at squash-merge time. With single-agent runs, the invariant is exact: every agent execution sees a worktree synchronised with `target` at the moment of dispatch.

The existing catch-up rebase inside `squash_merge` is retained — it covers the multi-agent case where `target` advances *during* agent execution because of another concurrent task's squash.
```

- [ ] **Step 3: Update the "Resume preference" entry under Key Conventions**

Find the bullet starting "**Resume preference** (`git.prefer_resumable: true`...". Append a final sentence:

```
Independent of the staleness gate, every dispatched worktree (fresh or resumed) is run through `sync_worktree_with_target` before the agent starts; conflicts there fail the task immediately with a structured `resume_conflict:` error rather than letting the agent run on stale state.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document pre-dispatch worktree sync invariant"
```

### Task 7: Update `docs/commands.md`

**Files:**
- Modify: `docs/commands.md` (the `claw-forge run` section, the `claw-forge worktrees` section if applicable)

- [ ] **Step 1: Inspect the existing structure**

Run: `grep -n '^##\|^###' docs/commands.md | head -40`

Find the `claw-forge run` section heading. Identify where failure modes are listed (search for `error_message` or `failed`).

- [ ] **Step 2: Add a paragraph on `resume_conflict` failure**

Under `claw-forge run`, in whichever subsection currently documents task failure modes, add:

```markdown
**`resume_conflict` failures.** When a previously-interrupted task is resumed, the dispatcher attempts a catch-up merge of the target branch into the feature branch *before* starting the agent. If the catch-up hits real content conflicts (both `target` and the branch modified the same lines of the same file since they diverged), the task is marked `failed` with an `error_message` starting with `resume_conflict:` and listing the conflicting files. The worktree is preserved so you can:

```bash
cd .claw-forge/worktrees/<slug>
git merge <target>           # produces conflict markers
# resolve conflicts in your editor
git add -A && git commit --no-verify
```

After committing the resolution, requeue the task (Reset All on the Failed column in the Kanban UI, or `claw-forge fix`). The next dispatch will sync cleanly because the resolution commit is now on the feature branch.

If you instead want to discard the partial work and start fresh, `claw-forge worktrees prune --discard` will drop the branch and worktree, and the task's next retry will recreate them from current `target`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/commands.md
git commit -m "docs(commands): document resume_conflict failure + recovery"
```

### Task 8: Update `README.md` if it lists run-flow ordering

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Check whether the README lists the run flow**

Run: `grep -n "create_worktree\|worktree\|run flow\|How a.*run" README.md | head -10`

If there is a "How a `claw-forge run` works" or equivalent ordered list, find it.

- [ ] **Step 2: Add the sync step (only if such a list exists)**

If the README does have the run-flow list, insert a step between worktree creation and agent dispatch:

```markdown
N. **Pre-dispatch sync**: the freshly-created (or resumed) worktree is brought up to date with the target branch via `git merge`. Resume conflicts fail the task immediately rather than wasting an agent turn on stale state.
```

If the README does **not** list the flow that granularly, skip this task — no change required.

- [ ] **Step 3: Commit (if changes were made)**

```bash
git add README.md
git commit -m "docs(readme): mention pre-dispatch worktree sync in run flow"
```

If no changes were needed, skip the commit and just record in the PR description that README required no update.

---

## Self-Review Checklist (run before handoff)

- [ ] **Spec coverage:** Every requirement in the user request — "draft plan for pre-resume rebase + file-overlap staleness, ensure no merge conflict for one running agent" — has a task. The pre-resume rebase = Tasks 2, 3, 4, 5. The file-overlap helper = Task 1. The single-agent guarantee is asserted in the architecture section and exercised by the integration test in Task 4.
- [ ] **Placeholder scan:** No `TODO`, `TBD`, "implement later", or "similar to Task N" without code.
- [ ] **Type consistency:** `sync_worktree_with_target` returns `dict[str, Any]` consistently in the function definition (Task 2), the test assertions (Task 2), and the `GitOps.sync_worktree` wrapper (Task 3). Result keys (`synced`, `no_op`, `merged_count`, `conflicts`, `dirty_worktree`) are referenced consistently in Tasks 2, 3, 4, 5, and 6.
- [ ] **Docs included:** Phase 5 has explicit tasks for `CLAUDE.md`, `docs/commands.md`, and a conditional `README.md` task — per the existing project convention that new behaviour requires doc updates.

---

## Out of Scope (call-outs for follow-up)

- **Scheduler-level overlap signal.** The plan adds `branch_overlap_files` for diagnostics but does **not** wire it into `_apply_resumable_flag` to skip resumption when overlap is high. With the dispatch-time sync in place, the overlap signal is a quality-of-life improvement (would let the scheduler prefer a different task at equal priority instead of letting the user hit a `resume_conflict` failure they'll then have to manually recover). Suggest a follow-up plan after this lands and we have telemetry on how often `resume_conflict` fires in practice.
- **LLM auto-resolution.** `claw_forge/git/conflict_advisor.py` already drafts a `CONFLICT_PROPOSAL.md` for *post-squash* conflicts. Extending it to also draft a proposal on `resume_conflict` is straightforward — the advisor's input is a list of files and content blobs, which we already have here — but is a separate piece of work and deliberately not part of this plan.
- **Multi-agent worktree sync.** This plan does not change the multi-agent case. The existing file-claim locks (`touches_files`) plus the catch-up rebase inside `squash_merge` already cover it; the new sync only adds a *pre-dispatch* checkpoint, not a *between-task* one. If we observe the same failure pattern in multi-agent runs (target moves between sync and squash), a follow-up could call `sync_worktree` again right before `squash_merge` runs.
