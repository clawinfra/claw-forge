"""Tests for claw_forge.git.repo — init_or_detect, ensure_gitignore."""

from __future__ import annotations

import subprocess
from pathlib import Path

from claw_forge.git.repo import _detect_default_branch, ensure_gitignore, init_or_detect


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

    def test_appends_newline_when_missing(self, tmp_path: Path) -> None:
        """When existing .gitignore doesn't end with newline, one is prepended."""
        (tmp_path / ".gitignore").write_text("*.pyc")  # no trailing \n
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert content.startswith("*.pyc\n")
        assert ".claw-forge/state.log" in content


class TestDetectDefaultBranch:
    def test_returns_main_in_non_repo(self, tmp_path: Path) -> None:
        """Fallback to 'main' when not a git repo."""
        result = _detect_default_branch(tmp_path)
        assert result == "main"
