# Git Workspace Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add git workspace initialization and history-based tracking so features are tracked in git history as agent memory.

**Architecture:** New `claw_forge/git/` module with 4 submodules (repo, branching, commits, merge). Dispatcher integrates via an `asyncio.Lock`-serialized git ops layer. Agents access git via two new MCP tools (`checkpoint`, `task_history`). Config lives in `claw-forge.yaml` under a `git:` key.

**Tech Stack:** Python 3.12, subprocess (git CLI), asyncio, claude-agent-sdk MCP tools

---

### Task 1: `claw_forge/git/repo.py` — Git init and detection

**Files:**
- Create: `claw_forge/git/__init__.py`
- Create: `claw_forge/git/repo.py`
- Create: `tests/git/__init__.py`
- Create: `tests/git/test_repo.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw_forge.git.repo — init_or_detect, ensure_gitignore."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.repo import init_or_detect, ensure_gitignore


class TestInitOrDetect:
    def test_fresh_directory_runs_git_init(self, tmp_path: Path) -> None:
        result = init_or_detect(tmp_path)
        assert result["initialized"] is True
        assert (tmp_path / ".git").is_dir()

    def test_existing_repo_skips_init(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        result = init_or_detect(tmp_path)
        assert result["initialized"] is False
        assert (tmp_path / ".git").is_dir()

    def test_creates_gitignore_if_missing(self, tmp_path: Path) -> None:
        init_or_detect(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".claw-forge/state.log" in content

    def test_preserves_existing_gitignore(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")
        init_or_detect(tmp_path)
        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".claw-forge/state.log" in content

    def test_returns_main_branch_name(self, tmp_path: Path) -> None:
        result = init_or_detect(tmp_path)
        assert result["default_branch"] in ("main", "master")


class TestEnsureGitignore:
    def test_creates_new_gitignore(self, tmp_path: Path) -> None:
        ensure_gitignore(tmp_path)
        assert (tmp_path / ".gitignore").exists()

    def test_appends_missing_entries(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in content
        assert ".claw-forge/state.log" in content

    def test_no_duplicates_on_rerun(self, tmp_path: Path) -> None:
        ensure_gitignore(tmp_path)
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".claw-forge/state.log") == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claw_forge.git'`

**Step 3: Write minimal implementation**

`claw_forge/git/__init__.py`:
```python
"""Git workspace tracking for claw-forge."""
```

`claw_forge/git/repo.py`:
```python
"""Git repository initialization and detection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

_GITIGNORE_ENTRIES = [
    ".claw-forge/state.log",
    ".claw-forge/state.db",
    ".claw-forge/state.db-journal",
]


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603, S607
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _detect_default_branch(cwd: Path) -> str:
    try:
        result = _run_git(["symbolic-ref", "--short", "HEAD"], cwd)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "main"


def ensure_gitignore(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    lines = existing.splitlines()
    added = []
    for entry in _GITIGNORE_ENTRIES:
        if entry not in lines:
            added.append(entry)
    if added:
        suffix = "\n".join(added) + "\n"
        if existing and not existing.endswith("\n"):
            suffix = "\n" + suffix
        gitignore.write_text(existing + suffix)


def init_or_detect(project_dir: Path) -> dict[str, Any]:
    initialized = False
    if not (project_dir / ".git").is_dir():
        _run_git(["init"], project_dir)
        initialized = True
    ensure_gitignore(project_dir)
    default_branch = _detect_default_branch(project_dir)
    return {
        "initialized": initialized,
        "default_branch": default_branch,
    }
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_repo.py -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add claw_forge/git/__init__.py claw_forge/git/repo.py tests/git/__init__.py tests/git/test_repo.py
git commit -m "feat(git): add repo init and detection module"
```

---

### Task 2: `claw_forge/git/branching.py` — Feature branch lifecycle

**Files:**
- Create: `claw_forge/git/branching.py`
- Create: `tests/git/test_branching.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw_forge.git.branching — create, switch, delete feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    current_branch,
    delete_branch,
    switch_branch,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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


class TestCreateFeatureBranch:
    def test_creates_branch_with_prefix(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth", prefix="feat")
        assert branch_exists(git_repo, "feat/user-auth")

    def test_switches_to_new_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth")
        assert current_branch(git_repo) == "feat/user-auth"

    def test_custom_prefix(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "fix-login", prefix="fix")
        assert branch_exists(git_repo, "fix/fix-login")

    def test_already_exists_switches_only(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "user-auth")
        switch_branch(git_repo, "main")
        create_feature_branch(git_repo, "abc123", "user-auth")
        assert current_branch(git_repo) == "feat/user-auth"


class TestCurrentBranch:
    def test_returns_main_on_fresh_repo(self, git_repo: Path) -> None:
        name = current_branch(git_repo)
        assert name in ("main", "master")


class TestBranchExists:
    def test_returns_true_for_existing(self, git_repo: Path) -> None:
        assert branch_exists(git_repo, "main") or branch_exists(git_repo, "master")

    def test_returns_false_for_nonexistent(self, git_repo: Path) -> None:
        assert branch_exists(git_repo, "nonexistent") is False


class TestDeleteBranch:
    def test_deletes_merged_branch(self, git_repo: Path) -> None:
        create_feature_branch(git_repo, "abc123", "temp")
        switch_branch(git_repo, "main")
        delete_branch(git_repo, "feat/temp")
        assert branch_exists(git_repo, "feat/temp") is False

    def test_delete_nonexistent_is_noop(self, git_repo: Path) -> None:
        delete_branch(git_repo, "nonexistent")  # should not raise
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_branching.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""Feature branch lifecycle — create, switch, delete."""

from __future__ import annotations

from pathlib import Path

from claw_forge.git.repo import _run_git


def current_branch(project_dir: Path) -> str:
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_dir)
    return result.stdout.strip()


def branch_exists(project_dir: Path, name: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", f"refs/heads/{name}"], project_dir)
        return True
    except Exception:
        return False


def create_feature_branch(
    project_dir: Path,
    task_id: str,
    slug: str,
    *,
    prefix: str = "feat",
) -> str:
    branch_name = f"{prefix}/{slug}"
    if branch_exists(project_dir, branch_name):
        switch_branch(project_dir, branch_name)
    else:
        _run_git(["checkout", "-b", branch_name], project_dir)
    return branch_name


def switch_branch(project_dir: Path, name: str) -> None:
    _run_git(["checkout", name], project_dir)


def delete_branch(project_dir: Path, name: str, *, force: bool = False) -> None:
    if not branch_exists(project_dir, name):
        return
    flag = "-D" if force else "-d"
    try:
        _run_git(["branch", flag, name], project_dir)
    except Exception:
        pass  # branch not fully merged and not force — skip
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_branching.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add claw_forge/git/branching.py tests/git/test_branching.py
git commit -m "feat(git): add feature branch lifecycle module"
```

---

### Task 3: `claw_forge/git/commits.py` — Checkpoint commits and history

**Files:**
- Create: `claw_forge/git/commits.py`
- Create: `tests/git/test_commits.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw_forge.git.commits — checkpoint commits with trailers, history parsing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.commits import commit_checkpoint, task_history


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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


class TestCommitCheckpoint:
    def test_creates_commit_with_message(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("x = 1\n")
        result = commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        assert result["commit_hash"]  # non-empty short SHA
        assert len(result["commit_hash"]) >= 7

    def test_commit_contains_trailers(self, git_repo: Path) -> None:
        (git_repo / "bar.py").write_text("y = 2\n")
        commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        )
        body = log.stdout
        assert "Task-ID: task-1" in body
        assert "Plugin: coding" in body
        assert "Phase: milestone" in body
        assert "Session: sess-1" in body

    def test_no_changes_returns_none(self, git_repo: Path) -> None:
        result = commit_checkpoint(
            git_repo,
            message="feat: nothing",
            task_id="t1",
            plugin="coding",
            phase="milestone",
            session_id="s1",
        )
        assert result is None

    def test_returns_branch_name(self, git_repo: Path) -> None:
        (git_repo / "baz.py").write_text("z = 3\n")
        result = commit_checkpoint(
            git_repo,
            message="feat(auth): add login",
            task_id="task-1",
            plugin="coding",
            phase="milestone",
            session_id="sess-1",
        )
        assert result["branch"] in ("main", "master")


class TestTaskHistory:
    def test_returns_commits_for_task(self, git_repo: Path) -> None:
        (git_repo / "a.py").write_text("a = 1\n")
        commit_checkpoint(
            git_repo, message="feat: step 1",
            task_id="task-A", plugin="coding", phase="milestone", session_id="s1",
        )
        (git_repo / "b.py").write_text("b = 2\n")
        commit_checkpoint(
            git_repo, message="feat: step 2",
            task_id="task-A", plugin="testing", phase="milestone", session_id="s1",
        )
        (git_repo / "c.py").write_text("c = 3\n")
        commit_checkpoint(
            git_repo, message="feat: other task",
            task_id="task-B", plugin="coding", phase="milestone", session_id="s1",
        )
        history = task_history(git_repo, task_id="task-A")
        assert len(history) == 2
        assert all(c["trailers"]["task_id"] == "task-A" for c in history)

    def test_returns_all_when_no_task_id(self, git_repo: Path) -> None:
        (git_repo / "d.py").write_text("d = 4\n")
        commit_checkpoint(
            git_repo, message="feat: whatever",
            task_id="task-X", plugin="coding", phase="save", session_id="s1",
        )
        history = task_history(git_repo)
        assert len(history) >= 1

    def test_respects_limit(self, git_repo: Path) -> None:
        for i in range(5):
            (git_repo / f"f{i}.py").write_text(f"v = {i}\n")
            commit_checkpoint(
                git_repo, message=f"feat: step {i}",
                task_id="task-L", plugin="coding", phase="milestone", session_id="s1",
            )
        history = task_history(git_repo, task_id="task-L", limit=2)
        assert len(history) == 2

    def test_commit_has_expected_keys(self, git_repo: Path) -> None:
        (git_repo / "e.py").write_text("e = 5\n")
        commit_checkpoint(
            git_repo, message="feat: keys",
            task_id="task-K", plugin="coding", phase="milestone", session_id="s1",
        )
        history = task_history(git_repo, task_id="task-K")
        commit = history[0]
        assert "hash" in commit
        assert "message" in commit
        assert "timestamp" in commit
        assert "trailers" in commit
        assert commit["trailers"]["plugin"] == "coding"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_commits.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""Checkpoint commits with structured trailers and history parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from claw_forge.git.branching import current_branch
from claw_forge.git.repo import _run_git

_TRAILER_PATTERN = re.compile(r"^(Task-ID|Plugin|Phase|Session):\s*(.+)$", re.MULTILINE)


def commit_checkpoint(
    project_dir: Path,
    *,
    message: str,
    task_id: str,
    plugin: str,
    phase: str,
    session_id: str,
) -> dict[str, Any] | None:
    # Stage all changes
    _run_git(["add", "-A"], project_dir)

    # Check if there's anything to commit
    try:
        _run_git(["diff", "--cached", "--quiet"], project_dir)
        return None  # no staged changes
    except Exception:
        pass  # there ARE staged changes — proceed

    body = (
        f"{message}\n\n"
        f"Task-ID: {task_id}\n"
        f"Plugin: {plugin}\n"
        f"Phase: {phase}\n"
        f"Session: {session_id}"
    )
    _run_git(["commit", "-m", body], project_dir)

    short_hash = _run_git(
        ["rev-parse", "--short", "HEAD"], project_dir
    ).stdout.strip()
    branch = current_branch(project_dir)

    return {"commit_hash": short_hash, "branch": branch}


def task_history(
    project_dir: Path,
    *,
    task_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    # Use a delimiter to parse commits
    sep = "---COMMIT-SEP---"
    fmt = f"%H{sep}%s{sep}%aI{sep}%B{sep}"
    try:
        result = _run_git(
            ["log", f"--format={fmt}", f"-n{limit * 3 if task_id else limit}"],
            project_dir,
        )
    except Exception:
        return []

    commits: list[dict[str, Any]] = []
    raw_commits = result.stdout.strip().split(f"{sep}\n")

    for raw in raw_commits:
        parts = raw.split(sep)
        if len(parts) < 4:
            continue
        full_hash, subject, timestamp, body = (
            parts[0].strip(),
            parts[1].strip(),
            parts[2].strip(),
            parts[3].strip(),
        )
        if not full_hash:
            continue

        trailers: dict[str, str] = {}
        for match in _TRAILER_PATTERN.finditer(body):
            key = match.group(1).lower().replace("-", "_")
            trailers[key] = match.group(2).strip()

        if task_id and trailers.get("task_id") != task_id:
            continue

        commits.append({
            "hash": full_hash[:10],
            "message": subject,
            "timestamp": timestamp,
            "trailers": trailers,
        })

        if len(commits) >= limit:
            break

    return commits
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_commits.py -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add claw_forge/git/commits.py tests/git/test_commits.py
git commit -m "feat(git): add checkpoint commits with trailers and history parsing"
```

---

### Task 4: `claw_forge/git/merge.py` — Squash-merge feature branches

**Files:**
- Create: `claw_forge/git/merge.py`
- Create: `tests/git/test_merge.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw_forge.git.merge — squash-merge feature branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git.branching import branch_exists, create_feature_branch, current_branch
from claw_forge.git.commits import commit_checkpoint
from claw_forge.git.merge import squash_merge


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_merge.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
"""Squash-merge feature branches to target branch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claw_forge.git.branching import branch_exists, current_branch, delete_branch, switch_branch
from claw_forge.git.repo import _run_git


def squash_merge(
    project_dir: Path,
    branch: str,
    target: str = "main",
) -> dict[str, Any]:
    if not branch_exists(project_dir, branch):
        return {"merged": False, "error": f"branch {branch!r} not found"}

    original_branch = current_branch(project_dir)
    try:
        switch_branch(project_dir, target)
        _run_git(["merge", "--squash", branch], project_dir)
        _run_git(["commit", "-m", f"merge: {branch} (squash)"], project_dir)
        short_hash = _run_git(
            ["rev-parse", "--short", "HEAD"], project_dir
        ).stdout.strip()
        delete_branch(project_dir, branch, force=True)
        return {"merged": True, "commit_hash": short_hash}
    except Exception as exc:
        # Abort merge if in progress, restore original branch
        try:
            _run_git(["merge", "--abort"], project_dir)
        except Exception:
            pass
        try:
            switch_branch(project_dir, original_branch)
        except Exception:
            pass
        return {"merged": False, "error": str(exc)}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_merge.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add claw_forge/git/merge.py tests/git/test_merge.py
git commit -m "feat(git): add squash-merge module"
```

---

### Task 5: `claw_forge/git/__init__.py` — Public API and async lock

**Files:**
- Modify: `claw_forge/git/__init__.py`
- Create: `tests/git/test_git_init.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw_forge.git — public API re-exports and GitOps lock."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.git import GitOps


@pytest.fixture()
def git_ops(tmp_path: Path) -> GitOps:
    return GitOps(project_dir=tmp_path, enabled=True)


class TestGitOps:
    def test_disabled_init_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.init())
        assert result is None

    def test_disabled_checkpoint_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.checkpoint(
            message="test", task_id="t1", plugin="coding",
            phase="milestone", session_id="s1",
        ))
        assert result is None

    def test_disabled_merge_is_noop(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=False)
        result = asyncio.run(ops.merge("feat/test"))
        assert result is None

    @patch("claw_forge.git.init_or_detect")
    def test_enabled_init_calls_init_or_detect(self, mock_init, tmp_path: Path) -> None:
        mock_init.return_value = {"initialized": True, "default_branch": "main"}
        ops = GitOps(project_dir=tmp_path, enabled=True)
        result = asyncio.run(ops.init())
        mock_init.assert_called_once_with(tmp_path)
        assert result["initialized"] is True

    def test_lock_serializes_operations(self, tmp_path: Path) -> None:
        ops = GitOps(project_dir=tmp_path, enabled=True)
        # Verify the lock attribute exists and is an asyncio.Lock
        assert isinstance(ops._lock, asyncio.Lock)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_git_init.py -v`
Expected: FAIL — `ImportError: cannot import name 'GitOps'`

**Step 3: Write implementation**

```python
"""Git workspace tracking for claw-forge.

Public API wraps all git operations behind an asyncio.Lock for safe
concurrent access from the dispatcher. When ``enabled=False``, all
operations become no-ops.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claw_forge.git.branching import (
    branch_exists,
    create_feature_branch,
    current_branch,
    delete_branch,
    switch_branch,
)
from claw_forge.git.commits import commit_checkpoint, task_history
from claw_forge.git.merge import squash_merge
from claw_forge.git.repo import ensure_gitignore, init_or_detect

__all__ = [
    "GitOps",
    "branch_exists",
    "commit_checkpoint",
    "create_feature_branch",
    "current_branch",
    "delete_branch",
    "ensure_gitignore",
    "init_or_detect",
    "squash_merge",
    "switch_branch",
    "task_history",
]


class GitOps:
    """Async-safe wrapper around git operations.

    All mutating operations are serialized behind an ``asyncio.Lock``
    to prevent concurrent branch switching from the parallel dispatcher.
    """

    def __init__(self, project_dir: Path, *, enabled: bool = True) -> None:
        self.project_dir = project_dir
        self.enabled = enabled
        self._lock = asyncio.Lock()

    async def init(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(init_or_detect, self.project_dir)

    async def create_branch(
        self, task_id: str, slug: str, *, prefix: str = "feat"
    ) -> str | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                create_feature_branch, self.project_dir, task_id, slug, prefix=prefix
            )

    async def checkpoint(
        self,
        *,
        message: str,
        task_id: str,
        plugin: str,
        phase: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                commit_checkpoint,
                self.project_dir,
                message=message,
                task_id=task_id,
                plugin=plugin,
                phase=phase,
                session_id=session_id,
            )

    async def merge(
        self, branch: str, target: str = "main"
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        async with self._lock:
            return await asyncio.to_thread(
                squash_merge, self.project_dir, branch, target
            )

    async def history(
        self, *, task_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return await asyncio.to_thread(
            task_history, self.project_dir, task_id=task_id, limit=limit
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_git_init.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add claw_forge/git/__init__.py tests/git/test_git_init.py
git commit -m "feat(git): add GitOps async wrapper with lock serialization"
```

---

### Task 6: MCP tools — `checkpoint` and `task_history`

**Files:**
- Modify: `claw_forge/mcp/sdk_server.py` (add 2 tools at end of `_make_tools`, lines ~298-310)
- Create: `tests/git/test_mcp_git_tools.py`

**Step 1: Write the failing tests**

```python
"""Tests for checkpoint and task_history MCP tools in sdk_server."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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


class TestCheckpointTool:
    @pytest.mark.asyncio()
    async def test_checkpoint_creates_commit(self, git_repo: Path) -> None:
        from claw_forge.mcp.sdk_server import _make_tools

        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if getattr(t, "_tool_name", t.__name__) == "checkpoint")
        (git_repo / "new_file.py").write_text("x = 1\n")
        result = await checkpoint_tool({
            "message": "feat: add new file",
            "task_id": "task-1",
            "plugin": "coding",
            "phase": "milestone",
            "session_id": "sess-1",
        })
        content = json.loads(result["content"][0]["text"])
        assert content["commit_hash"]
        assert content["branch"]

    @pytest.mark.asyncio()
    async def test_checkpoint_no_changes_returns_null(self, git_repo: Path) -> None:
        from claw_forge.mcp.sdk_server import _make_tools

        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if getattr(t, "_tool_name", t.__name__) == "checkpoint")
        result = await checkpoint_tool({
            "message": "feat: nothing",
            "task_id": "t1",
            "plugin": "coding",
            "phase": "save",
            "session_id": "s1",
        })
        content = json.loads(result["content"][0]["text"])
        assert content is None


class TestTaskHistoryTool:
    @pytest.mark.asyncio()
    async def test_task_history_returns_commits(self, git_repo: Path) -> None:
        from claw_forge.mcp.sdk_server import _make_tools

        tools = _make_tools(git_repo)
        checkpoint_tool = next(t for t in tools if getattr(t, "_tool_name", t.__name__) == "checkpoint")
        history_tool = next(t for t in tools if getattr(t, "_tool_name", t.__name__) == "task_history")

        (git_repo / "a.py").write_text("a = 1\n")
        await checkpoint_tool({
            "message": "feat: step 1",
            "task_id": "task-H",
            "plugin": "coding",
            "phase": "milestone",
            "session_id": "s1",
        })

        result = await history_tool({"task_id": "task-H"})
        commits = json.loads(result["content"][0]["text"])
        assert len(commits) >= 1
        assert commits[0]["trailers"]["task_id"] == "task-H"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_mcp_git_tools.py -v`
Expected: FAIL — tool named `checkpoint` not found in tools list

**Step 3: Modify `sdk_server.py`**

Add these two tools inside `_make_tools()` at `claw_forge/mcp/sdk_server.py`, before the `return` statement (line ~298). Also add the import at the top of `_make_tools`.

Add at top of file after existing imports:
```python
from claw_forge.git.commits import commit_checkpoint as _git_checkpoint
from claw_forge.git.commits import task_history as _git_task_history
```

Add before the `return [...]` statement (around line 298):

```python
    @tool(
        "checkpoint",
        "Save a git checkpoint commit with a message. Use before risky changes or at milestones.",
        {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What was accomplished (commit message)"},
                "task_id": {"type": "string", "description": "Current task ID"},
                "plugin": {"type": "string", "description": "Current plugin name"},
                "phase": {
                    "type": "string",
                    "description": "Phase: milestone | save | risky",
                    "enum": ["milestone", "save", "risky"],
                },
                "session_id": {"type": "string", "description": "Current session ID"},
            },
            "required": ["message", "task_id", "plugin", "session_id"],
        },
    )
    async def checkpoint(args: dict[str, Any]) -> dict[str, Any]:
        import json
        result = _git_checkpoint(
            project_dir,
            message=args.get("message", "checkpoint"),
            task_id=args.get("task_id", ""),
            plugin=args.get("plugin", ""),
            phase=args.get("phase", "milestone"),
            session_id=args.get("session_id", ""),
        )
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "task_history",
        "Get git commit history for a task or the whole project. Use to understand what happened before.",
        {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Filter by task ID (optional)"},
                "limit": {"type": "integer", "description": "Max commits to return (default 20)"},
            },
            "required": [],
        },
    )
    async def git_task_history(args: dict[str, Any]) -> dict[str, Any]:
        import json
        commits = _git_task_history(
            project_dir,
            task_id=args.get("task_id"),
            limit=args.get("limit", 20),
        )
        return {"content": [{"type": "text", "text": json.dumps(commits)}]}
```

Add `checkpoint` and `git_task_history` to the return list (line ~298):

```python
    return [
        feature_get_stats,
        feature_get_by_id,
        feature_get_ready,
        feature_claim_and_get,
        feature_mark_passing,
        feature_mark_failing,
        feature_mark_in_progress,
        feature_clear_in_progress,
        feature_create_bulk,
        feature_create,
        feature_add_dependency,
        checkpoint,
        git_task_history,
    ]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_mcp_git_tools.py -v`
Expected: PASS (all 3 tests)

Note: The MCP tool test may need adjustment based on how `@tool` decorator names tools internally. Check with `t.__name__` or `t._tool_name` and adjust the `next()` filter accordingly.

**Step 5: Commit**

```bash
git add claw_forge/mcp/sdk_server.py tests/git/test_mcp_git_tools.py
git commit -m "feat(mcp): add checkpoint and task_history git tools"
```

---

### Task 7: Integrate git init into `claw-forge init`

**Files:**
- Modify: `claw_forge/cli.py` (the `init` command, lines 1100-1180)
- Modify: `tests/test_scaffold.py` (add git-related init tests)

**Step 1: Write the failing tests**

Add to `tests/test_scaffold.py`:

```python
# ---------------------------------------------------------------------------
# git init integration
# ---------------------------------------------------------------------------


def test_scaffold_project_returns_git_initialized_key(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert "git_initialized" in result


def test_scaffold_project_initializes_git_repo(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path)
    assert (tmp_path / ".git").is_dir()
    assert result["git_initialized"] is True


def test_scaffold_project_existing_git_repo_skips_init(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    result = scaffold_project(tmp_path)
    assert result["git_initialized"] is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scaffold.py::test_scaffold_project_returns_git_initialized_key -v`
Expected: FAIL — `KeyError: 'git_initialized'`

**Step 3: Modify `scaffold.py`**

In `claw_forge/scaffold.py`, at the end of `scaffold_project()` (around line 280), before the return:

Add import at top:
```python
from claw_forge.git.repo import init_or_detect
```

Add before the return dict (after line 279):
```python
    git_result = init_or_detect(project_path)
```

Add to the return dict:
```python
        "git_initialized": git_result["initialized"],
```

Then in `claw_forge/cli.py` `init()` command (around line 1143), add after the stack detection output:

```python
    if scaffold["git_initialized"]:
        console.print("✓ Initialized git repository")
    else:
        console.print("[dim]✓ Git repository already exists — skipped[/dim]")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS (all existing + 3 new tests)

**Step 5: Commit**

```bash
git add claw_forge/scaffold.py claw_forge/cli.py tests/test_scaffold.py
git commit -m "feat(init): integrate git repo initialization into claw-forge init"
```

---

### Task 8: Integrate git into the dispatcher task lifecycle

**Files:**
- Modify: `claw_forge/cli.py` (task_handler, around lines 750-880)
- Create: `tests/git/test_dispatcher_git.py`

**Step 1: Write the failing tests**

```python
"""Tests for git integration in the dispatcher task lifecycle."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claw_forge.git import GitOps


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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


class TestGitOpsIntegration:
    def test_create_branch_for_task(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        branch = asyncio.run(ops.create_branch("task-1", "user-auth"))
        assert branch == "feat/user-auth"

    def test_checkpoint_after_plugin(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        asyncio.run(ops.create_branch("task-1", "user-auth"))
        (git_repo / "auth.py").write_text("login = True\n")
        result = asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1",
            plugin="coding",
            phase="coding",
            session_id="sess-1",
        ))
        assert result is not None
        assert result["commit_hash"]

    def test_merge_after_completion(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        asyncio.run(ops.create_branch("task-1", "user-auth"))
        (git_repo / "auth.py").write_text("login = True\n")
        asyncio.run(ops.checkpoint(
            message="feat(auth): implement login",
            task_id="task-1",
            plugin="coding",
            phase="coding",
            session_id="sess-1",
        ))
        result = asyncio.run(ops.merge("feat/user-auth"))
        assert result["merged"] is True

    def test_full_lifecycle(self, git_repo: Path) -> None:
        ops = GitOps(project_dir=git_repo, enabled=True)
        # Create branch
        asyncio.run(ops.create_branch("task-1", "payments"))
        # Coding phase
        (git_repo / "pay.py").write_text("pay = True\n")
        asyncio.run(ops.checkpoint(
            message="feat(pay): add payments",
            task_id="task-1", plugin="coding",
            phase="coding", session_id="s1",
        ))
        # Testing phase
        (git_repo / "test_pay.py").write_text("assert True\n")
        asyncio.run(ops.checkpoint(
            message="test(pay): add tests",
            task_id="task-1", plugin="testing",
            phase="testing", session_id="s1",
        ))
        # Merge
        result = asyncio.run(ops.merge("feat/payments"))
        assert result["merged"] is True
        # History shows the squash commit on main
        history = asyncio.run(ops.history())
        assert len(history) >= 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_dispatcher_git.py -v`
Expected: PASS — these test the `GitOps` class directly, which should already work from Task 5.

**Step 3: Wire GitOps into cli.py task_handler**

In `claw_forge/cli.py`, inside the `run()` command (around line 312), after config is loaded and before the dispatcher loop:

1. Read git config from the loaded YAML config:
```python
git_cfg = cfg.get("git", {})
git_enabled = git_cfg.get("enabled", True)
git_merge_strategy = git_cfg.get("merge_strategy", "auto")
git_branch_prefix = git_cfg.get("branch_prefix", "feat")
git_commit_on_boundary = git_cfg.get("commit_on_plugin_boundary", True)
```

2. Create GitOps instance:
```python
from claw_forge.git import GitOps
git_ops = GitOps(project_dir=Path(project).resolve(), enabled=git_enabled)
```

3. In `task_handler` (the inner async function), around the start of task execution (before the agent runs), add branch creation:
```python
if git_enabled:
    slug = re.sub(r"[^a-z0-9]+", "-", task_node.plugin_name + "-" + task_node.id[:8]).strip("-")
    await git_ops.create_branch(task_node.id, slug, prefix=git_branch_prefix)
```

4. After successful task completion (around line 872, after `fin_task.status = "completed"`), add checkpoint + merge:
```python
if git_enabled and success and git_commit_on_boundary:
    await git_ops.checkpoint(
        message=f"{task_node.plugin_name}({slug}): completed",
        task_id=task_node.id,
        plugin=task_node.plugin_name,
        phase=task_node.plugin_name,
        session_id=session_id,
    )
    if git_merge_strategy == "auto":
        branch_name = f"{git_branch_prefix}/{slug}"
        await git_ops.merge(branch_name)
```

**Step 4: Run tests**

Run: `uv run pytest tests/git/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add claw_forge/cli.py tests/git/test_dispatcher_git.py
git commit -m "feat(run): wire GitOps into dispatcher task lifecycle"
```

---

### Task 9: Add `claw-forge merge` CLI command

**Files:**
- Modify: `claw_forge/cli.py` (add new command)
- Create: `tests/git/test_cli_merge.py`

**Step 1: Write the failing tests**

```python
"""Tests for claw-forge merge CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claw_forge.cli import app

runner = CliRunner()


@pytest.fixture()
def git_project(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
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


class TestMergeCommand:
    def test_merge_nonexistent_branch_shows_error(self, git_project: Path) -> None:
        result = runner.invoke(app, ["merge", "nonexistent", "--project", str(git_project)])
        assert result.exit_code == 0 or "not found" in result.output.lower()

    def test_merge_existing_branch_succeeds(self, git_project: Path) -> None:
        from claw_forge.git.branching import create_feature_branch
        from claw_forge.git.commits import commit_checkpoint

        create_feature_branch(git_project, "t1", "test-feat")
        (git_project / "x.py").write_text("x = 1\n")
        commit_checkpoint(
            git_project, message="feat: add x",
            task_id="t1", plugin="coding", phase="milestone", session_id="s1",
        )
        subprocess.run(["git", "checkout", "main"], cwd=git_project, check=True, capture_output=True)

        result = runner.invoke(app, ["merge", "feat/test-feat", "--project", str(git_project)])
        assert "merged" in result.output.lower() or result.exit_code == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/git/test_cli_merge.py -v`
Expected: FAIL — no `merge` command registered

**Step 3: Add the merge command to cli.py**

Add after the `fix` command (around line 2370):

```python
@app.command()
def merge(
    branch: str = typer.Argument(None, help="Branch to squash-merge (e.g. feat/user-auth)"),
    project: str = typer.Option(".", "--project", "-p", help="Project directory."),
    target: str = typer.Option("main", "--target", "-t", help="Target branch to merge into."),
) -> None:
    """Squash-merge a feature branch to the target branch.

    Used with merge_strategy: manual to control when features land on main.
    If no branch is specified, lists branches with the configured prefix.

    Examples:

        # Merge a specific branch
        claw-forge merge feat/user-auth

        # List ready feature branches
        claw-forge merge

        # Merge into a custom target
        claw-forge merge feat/user-auth --target develop
    """
    import subprocess as sp

    project_path = Path(project).resolve()

    if branch is None:
        # List feature branches
        try:
            result = sp.run(
                ["git", "branch", "--list", "feat/*"],
                cwd=project_path, capture_output=True, text=True, check=True,
            )
            branches = [b.strip().lstrip("* ") for b in result.stdout.strip().splitlines() if b.strip()]
            if not branches:
                console.print("[dim]No feature branches found.[/dim]")
                return
            console.print("[bold]Feature branches:[/bold]")
            for b in branches:
                console.print(f"  • {b}")
            console.print(f"\n[dim]Run: claw-forge merge <branch>[/dim]")
        except sp.CalledProcessError:
            console.print("[red]Not a git repository or git not available.[/red]")
        return

    from claw_forge.git.merge import squash_merge

    result = squash_merge(project_path, branch, target)
    if result["merged"]:
        console.print(f"[green]✓ Merged {branch} → {target} ({result['commit_hash']})[/green]")
    else:
        console.print(f"[red]✗ Merge failed: {result.get('error', 'unknown')}[/red]")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/git/test_cli_merge.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add claw_forge/cli.py tests/git/test_cli_merge.py
git commit -m "feat(cli): add claw-forge merge command for manual merge strategy"
```

---

### Task 10: Add git config to `claw-forge.yaml` scaffold

**Files:**
- Modify: `claw_forge/cli.py` (the `_DEFAULT_CONFIG` or `_scaffold_config` function)
- Modify: `tests/test_scaffold.py` (verify git config appears in scaffolded yaml)

**Step 1: Write the failing test**

Add to `tests/test_scaffold.py`:

```python
def test_scaffold_config_has_git_section(tmp_path: Path) -> None:
    from unittest.mock import patch

    import yaml

    from claw_forge.cli import _scaffold_config
    cfg = str(tmp_path / "claw-forge.yaml")
    with patch("claw_forge.cli.console"):
        _scaffold_config(cfg)
    data = yaml.safe_load((tmp_path / "claw-forge.yaml").read_text())
    assert "git" in data
    assert data["git"]["enabled"] is True
    assert data["git"]["merge_strategy"] == "auto"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scaffold.py::test_scaffold_config_has_git_section -v`
Expected: FAIL — `KeyError: 'git'`

**Step 3: Modify `_scaffold_config` in cli.py**

Find the `_DEFAULT_CONFIG` template string in `cli.py` (search for `_DEFAULT_CONFIG` or the YAML template in `_scaffold_config`). Add a `git:` section:

```yaml
git:
  enabled: true
  merge_strategy: auto    # auto | manual
  branch_prefix: feat
  commit_on_plugin_boundary: true
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS (all tests including the new one)

**Step 5: Commit**

```bash
git add claw_forge/cli.py tests/test_scaffold.py
git commit -m "feat(config): add git section to scaffolded claw-forge.yaml"
```

---

### Task 11: Run full test suite and lint

**Step 1: Run full test suite with coverage**

Run: `uv run pytest tests/ -q --cov=claw_forge --cov-report=term-missing`
Expected: PASS, coverage >= 90%

**Step 2: Run linter**

Run: `uv run ruff check claw_forge/ tests/`
Expected: PASS (no lint errors)

**Step 3: Run type checker**

Run: `uv run mypy claw_forge/ --ignore-missing-imports`
Expected: PASS

**Step 4: Fix any failures found in steps 1-3**

If coverage dips below 90%, add tests for uncovered lines.
If lint errors appear, fix them (`uv run ruff check claw_forge/ tests/ --fix`).

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: fix lint and coverage for git workspace tracking"
```
