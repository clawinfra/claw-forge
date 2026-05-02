"""Tests for ``claw_forge.git.conflict_advisor`` — LLM advisory drafts.

These tests must not call the real Anthropic API in CI.  We monkey-patch
``_run_advisor_agent`` to a deterministic string so every assertion is on
the surrounding plumbing (file enumeration, prompt assembly, error
recovery), not on whatever the model happens to emit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claw_forge.git import conflict_advisor as advisor_mod
from claw_forge.git.branching import create_worktree
from claw_forge.git.commits import commit_checkpoint
from claw_forge.git.conflict_advisor import (
    _build_prompt,
    _collect_conflict_context,
    draft_conflict_proposal,
)


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


def _conflict_setup(git_repo: Path, slug: str = "x") -> tuple[str, Path]:
    """Create the canonical conflict scenario: README.md changed on both sides."""
    branch, wt = create_worktree(git_repo, f"task-{slug}", slug)
    (wt / "README.md").write_text("# from feature branch\n")
    commit_checkpoint(
        wt, message="readme on feature",
        task_id=f"task-{slug}", plugin="coding", phase="coding",
        session_id="s1",
    )
    (git_repo / "README.md").write_text("# from main\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "main change"],
        cwd=git_repo, check=True,
    )
    return branch, wt


class TestCollectConflictContext:
    def test_overlap_files_are_returned_with_three_versions(
        self, git_repo: Path,
    ) -> None:
        """The conflict-context builder returns ancestor + target + branch
        contents for every file changed on both sides since merge-base.
        """
        branch, _ = _conflict_setup(git_repo, "alpha")
        blocks = _collect_conflict_context(git_repo, branch, "main")
        assert len(blocks) == 1
        block = blocks[0]
        assert block["path"] == "README.md"
        assert block["ancestor"].strip() == "# init"
        assert block["target_content"].strip() == "# from main"
        assert block["branch_content"].strip() == "# from feature branch"
        assert block["target"] == "main"
        assert block["branch"] == branch

    def test_no_overlap_returns_empty(self, git_repo: Path) -> None:
        """If feature branch and main touch disjoint files, there's nothing
        for the advisor to draft against.
        """
        _, wt = create_worktree(git_repo, "task-disjoint", "disjoint")
        (wt / "feature.py").write_text("x = 1\n")
        commit_checkpoint(
            wt, message="add feature",
            task_id="task-disjoint", plugin="coding", phase="coding",
            session_id="s1",
        )
        (git_repo / "main_only.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "main only"],
            cwd=git_repo, check=True,
        )
        blocks = _collect_conflict_context(git_repo, "feat/disjoint", "main")
        assert blocks == []

    def test_unknown_branch_returns_empty(self, git_repo: Path) -> None:
        """Should not raise — graceful empty result on missing branch."""
        blocks = _collect_conflict_context(git_repo, "feat/nope", "main")
        assert blocks == []


class TestBuildPrompt:
    def test_prompt_contains_task_branch_target_files(self) -> None:
        prompt = _build_prompt(
            branch="feat/auth-jwt",
            target="main",
            task_description="Add JWT authentication",
            blocks=[{
                "path": "auth.py",
                "ancestor": "old\n",
                "target": "main",
                "target_content": "main side\n",
                "branch": "feat/auth-jwt",
                "branch_content": "branch side\n",
            }],
        )
        assert "feat/auth-jwt" in prompt
        assert "main" in prompt
        assert "Add JWT authentication" in prompt
        assert "auth.py" in prompt
        assert "old" in prompt
        assert "main side" in prompt
        assert "branch side" in prompt

    def test_prompt_handles_empty_description(self) -> None:
        prompt = _build_prompt(
            branch="feat/x", target="main",
            task_description="",
            blocks=[{
                "path": "x.py",
                "ancestor": "", "target": "main", "target_content": "",
                "branch": "feat/x", "branch_content": "",
            }],
        )
        assert "no description on file" in prompt


class TestDraftConflictProposal:
    def test_writes_proposal_when_advisor_returns_text(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Happy path: agent returns text, ``CONFLICT_PROPOSAL.md`` lands in
        the worktree directory.
        """
        branch, wt = _conflict_setup(git_repo, "happy")

        async def fake_agent(prompt: str, **kwargs: object) -> str:
            return "# Proposal\n- step 1\n- step 2\n"

        monkeypatch.setattr(advisor_mod, "_run_advisor_agent", fake_agent)

        path = draft_conflict_proposal(
            git_repo, wt, branch, "main",
            task={"description": "do the thing", "status": "failed"},
        )
        assert path is not None
        assert path.exists()
        assert path.name == "CONFLICT_PROPOSAL.md"
        assert "Proposal" in path.read_text()

    def test_returns_none_when_no_overlap(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Disjoint changes → no draft is needed, no agent call is made."""
        _, wt = create_worktree(git_repo, "task-no-overlap", "no-overlap")
        (wt / "feature.py").write_text("x = 1\n")
        commit_checkpoint(
            wt, message="add feature",
            task_id="task-no-overlap", plugin="coding", phase="coding",
            session_id="s1",
        )

        called = {"agent": False}

        async def fake_agent(prompt: str, **kwargs: object) -> str:
            called["agent"] = True
            return "should not be invoked"

        monkeypatch.setattr(advisor_mod, "_run_advisor_agent", fake_agent)
        path = draft_conflict_proposal(
            git_repo, wt, "feat/no-overlap", "main", task=None,
        )
        assert path is None
        assert called["agent"] is False

    def test_returns_none_when_agent_fails(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent exception → the function returns None, no file written.
        Cleanup loop's outer try/except expects this graceful failure.
        """
        branch, wt = _conflict_setup(git_repo, "bad")

        async def boom(prompt: str, **kwargs: object) -> str:
            raise RuntimeError("network kaput")

        monkeypatch.setattr(advisor_mod, "_run_advisor_agent", boom)
        path = draft_conflict_proposal(
            git_repo, wt, branch, "main", task=None,
        )
        assert path is None
        assert not (wt / "CONFLICT_PROPOSAL.md").exists()

    def test_returns_none_on_empty_agent_response(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty response is treated as "no proposal" — don't write an
        empty file the user has to delete.
        """
        branch, wt = _conflict_setup(git_repo, "empty")

        async def empty(prompt: str, **kwargs: object) -> str:
            return ""

        monkeypatch.setattr(advisor_mod, "_run_advisor_agent", empty)
        path = draft_conflict_proposal(
            git_repo, wt, branch, "main", task=None,
        )
        assert path is None
        assert not (wt / "CONFLICT_PROPOSAL.md").exists()


class TestDraftConflictProposalNestedLoop:
    """Regression for the v0.5.37 ``RuntimeError: asyncio.run() cannot be
    called from a running event loop`` bug.

    The smart-mode salvage hook (``smart_cleanup_worktrees`` in
    ``cli.py``) runs inside the dispatcher's ``async def main()``, which
    means there's already an active event loop when the advisor is
    invoked.  ``draft_conflict_proposal`` must therefore not assume
    sync-only callers — running the agent on a worker thread sidesteps
    the nested-loop trap.
    """

    @pytest.mark.asyncio
    async def test_works_when_called_from_running_event_loop(
        self,
        git_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        branch, wt = _conflict_setup(git_repo, "nested")

        async def fake_agent(prompt: str, **kwargs: object) -> str:
            return "# Proposal from inside a running loop\n"

        monkeypatch.setattr(advisor_mod, "_run_advisor_agent", fake_agent)

        # We are inside a running event loop here (pytest-asyncio).  Before
        # the fix, draft_conflict_proposal's bare asyncio.run call raised
        # ``RuntimeError: asyncio.run() cannot be called from a running
        # event loop`` and the function returned None — the user's v0.5.37
        # traceback.  The threaded helper makes this work.
        path = draft_conflict_proposal(
            git_repo, wt, branch, "main",
            task={"description": "nested loop test", "status": "failed"},
        )
        assert path is not None, (
            "draft_conflict_proposal returned None inside a running event "
            "loop — nested-loop fix is missing or regressed"
        )
        assert path.exists()
        assert "running loop" in path.read_text()


class TestRunAdvisorAgentBypassesRunAgent:
    """Regression for the v0.5.38 ``ValueError: can_use_tool callback
    requires streaming mode`` failure.

    The advisor must NOT route through ``claw_forge.agent.runner.run_agent``
    because that wrapper auto-attaches a ``can_use_tool`` callback (security
    hook for bash commands), which forces the SDK into streaming mode and
    rejects string prompts.  Test by monkey-patching the SDK's ``query``
    function and asserting on what it actually receives.
    """

    @pytest.mark.asyncio
    async def test_query_receives_string_prompt_and_no_can_use_tool(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import claude_agent_sdk

        from claw_forge.git.conflict_advisor import _run_advisor_agent

        captured: dict[str, object] = {}

        class _FakeResultMessage:
            def __init__(self, result: str) -> None:
                self.result = result

        # Rename the class to mimic the SDK's ResultMessage check.
        _FakeResultMessage.__name__ = "ResultMessage"

        async def fake_query(*, prompt: object, options: object):
            captured["prompt"] = prompt
            captured["prompt_type"] = type(prompt).__name__
            captured["can_use_tool"] = getattr(options, "can_use_tool", "MISSING")
            captured["mcp_servers"] = getattr(options, "mcp_servers", None)
            captured["max_turns"] = getattr(options, "max_turns", None)
            yield _FakeResultMessage("# fake proposal text")

        monkeypatch.setattr(claude_agent_sdk, "query", fake_query)

        text = await _run_advisor_agent("hello world prompt")

        assert text == "# fake proposal text"
        # The bug: prompt was a string but can_use_tool was set, so the SDK
        # raised ValueError.  Verify both properties are correct after the fix.
        assert captured["prompt_type"] == "str", (
            "prompt should be a plain str, not an AsyncIterable wrapper "
            f"(got {captured['prompt_type']})"
        )
        assert captured["can_use_tool"] is None, (
            "can_use_tool must be None on the advisor's options — otherwise "
            "the SDK requires streaming mode and rejects string prompts"
        )
        # The advisor doesn't need MCP servers either.  The default factory
        # returns an empty dict, not the project's configured servers.
        assert captured["mcp_servers"] == {} or captured["mcp_servers"] is None, (
            "advisor options must not inherit project MCP servers — "
            f"got {captured['mcp_servers']!r}"
        )
        assert captured["max_turns"] == 10
