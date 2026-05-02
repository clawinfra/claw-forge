"""LLM advisor that drafts a ``CONFLICT_PROPOSAL.md`` for a preserved
salvage-conflict worktree.

This is **advisory**, not authoritative.  When ``smart_cleanup_worktrees``
fails to squash-merge a feature branch into target due to a real content
conflict, the worktree + branch are preserved and the advisor (if enabled
via ``git.llm_conflict_proposals: true``) writes a markdown file inside
the preserved worktree with:

- The list of conflicting files
- Per-file: the common ancestor, the target side, the branch side
- A proposed unified resolution drafted by an agent

The user reads, edits, accepts, or rejects the proposal.  Nothing the
advisor produces lands on ``main`` automatically — that asymmetry is the
whole reason the design is advisory rather than auto-merging.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import subprocess
from pathlib import Path
from typing import Any

from claw_forge.git.repo import _run_git

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = """\
You are an experienced engineer drafting a merge-conflict resolution
proposal.  Two branches both modified one or more files; squash-merging
{branch} into {target} produced conflicts on overlapping changes.  You
will NOT commit anything — your output will be saved as a markdown
proposal the human operator reviews.

## Task that produced the feature branch
{task_description}

## Files in conflict
{files_section}

## Output format
Produce a single markdown document with this structure:

```
# Conflict resolution proposal: {branch} → {target}

## Summary
<2-3 sentences explaining what both sides were trying to do and the
strategy you took to reconcile them>

## File: <path>
### Proposed resolution
```<lang>
<full resolved file contents>
```
### Reasoning
<short explanation of which lines came from which side and why>

(repeat per conflicted file)

## Apply
```bash
# From inside the worktree (.claw-forge/worktrees/<slug>):
# Replace each file with the proposed contents above, then:
git add -A
git commit --no-verify -m "resolve: merge conflicts with {target}"
git checkout {target}
git merge --squash {branch}
git commit --no-verify -m "<your message>"
```
```

Be concrete.  Output the entire resolved file content, not a diff.
Prefer the side that preserves both intents when reconciliation is
possible.  Surface anything ambiguous you couldn't resolve as a TODO
the human must address.
"""


def _file_section(file_block: dict[str, str]) -> str:
    return (
        f"### `{file_block['path']}`\n\n"
        f"**Common ancestor:**\n```\n{file_block['ancestor']}\n```\n\n"
        f"**Target side ({file_block['target']}):**\n"
        f"```\n{file_block['target_content']}\n```\n\n"
        f"**Branch side ({file_block['branch']}):**\n"
        f"```\n{file_block['branch_content']}\n```\n"
    )


def _collect_conflict_context(
    project_dir: Path, branch: str, target: str,
) -> list[dict[str, str]]:
    """Identify files modified on both sides since their common ancestor.

    This is a heuristic — git itself only declares a real conflict during
    a merge attempt, but we already know one happened (squash failed).  The
    overlap of "files changed on target since merge-base" with "files
    changed on branch since merge-base" is the candidate set.
    """
    try:
        merge_base = _run_git(
            ["merge-base", target, branch], project_dir,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        logger.debug("Could not find merge-base for %s and %s", target, branch)
        return []
    if not merge_base:
        return []

    target_changed = set(
        _run_git(
            ["diff", "--name-only", merge_base, target], project_dir,
        ).stdout.splitlines()
    )
    branch_changed = set(
        _run_git(
            ["diff", "--name-only", merge_base, branch], project_dir,
        ).stdout.splitlines()
    )
    overlap = sorted(target_changed & branch_changed)

    blocks: list[dict[str, str]] = []
    for path in overlap:
        try:
            ancestor = _run_git(
                ["show", f"{merge_base}:{path}"], project_dir,
            ).stdout
        except subprocess.CalledProcessError:
            ancestor = "<file did not exist at merge-base>"
        try:
            target_content = _run_git(
                ["show", f"{target}:{path}"], project_dir,
            ).stdout
        except subprocess.CalledProcessError:
            target_content = "<file does not exist on target>"
        try:
            branch_content = _run_git(
                ["show", f"{branch}:{path}"], project_dir,
            ).stdout
        except subprocess.CalledProcessError:
            branch_content = "<file does not exist on branch>"
        blocks.append({
            "path": path,
            "ancestor": ancestor,
            "target": target,
            "target_content": target_content,
            "branch": branch,
            "branch_content": branch_content,
        })
    return blocks


def _build_prompt(
    branch: str,
    target: str,
    task_description: str,
    blocks: list[dict[str, str]],
) -> str:
    files_section = "\n".join(_file_section(b) for b in blocks)
    return _PROMPT_TEMPLATE.format(
        branch=branch,
        target=target,
        task_description=task_description or "(no description on file)",
        files_section=files_section,
    )


async def _run_advisor_agent(prompt: str, *, model: str | None = None) -> str:
    """Call ``claude_agent_sdk.query()`` directly with bare-minimum options.

    Deliberately bypasses ``claw_forge.agent.runner.run_agent`` because that
    wrapper auto-attaches a ``can_use_tool`` callback (security hook for
    bash commands), MCP servers, and CLAUDE.md/skill resolution.  Two
    problems for the advisor:

    1. ``can_use_tool`` flips the SDK into streaming mode, which requires
       an ``AsyncIterable`` prompt rather than a string.  Passing a string
       (which is all the advisor needs) raises ``ValueError: can_use_tool
       callback requires streaming mode``.
    2. The advisor doesn't *want* the agent to use any tools — the output
       is a markdown proposal text, not a code-edit operation.  Wiring up
       tools, MCP, skills, etc. is wasted setup and adds attack surface
       to a feature that doesn't need it.

    Minimal options + plain string prompt → SDK stays in non-streaming
    mode and returns ``ResultMessage`` containing the agent's text.
    """
    import claude_agent_sdk

    options_kwargs: dict[str, Any] = {"max_turns": 10}
    if model:
        options_kwargs["model"] = model
    options = claude_agent_sdk.ClaudeAgentOptions(**options_kwargs)

    result_text = ""
    async for message in claude_agent_sdk.query(prompt=prompt, options=options):
        if message.__class__.__name__ == "ResultMessage":
            result_text = getattr(message, "result", "") or ""
    return result_text


def _run_advisor_agent_blocking(
    prompt: str, *, model: str | None = None,
) -> str:
    """Run :func:`_run_advisor_agent` to completion regardless of whether
    the calling thread already has an active event loop.

    The smart-mode salvage hook in ``cli.py`` runs *inside* ``async def
    main()``, which means a bare ``asyncio.run(...)`` here would crash
    with ``RuntimeError: asyncio.run() cannot be called from a running
    event loop``.  Dispatching to a one-shot worker thread sidesteps the
    nested-loop issue: the worker thread has no loop of its own, so
    ``asyncio.run`` inside it works regardless of the caller's context.

    Tests that call :func:`draft_conflict_proposal` from sync test
    bodies still hit the same path; the threading is invisible to them.
    """
    def _target() -> str:
        return asyncio.run(_run_advisor_agent(prompt, model=model))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_target).result()


def draft_conflict_proposal(
    project_dir: Path,
    worktree_path: Path,
    branch: str,
    target: str,
    task: dict[str, Any] | None,
    *,
    model: str | None = None,
) -> Path | None:
    """Synchronous entry point invoked by ``smart_cleanup_worktrees``.

    Returns the path to the written proposal, or None if there were no
    overlapping files to draft for, or if the agent call failed (caller
    suppresses exceptions, so any errors here just produce a None return).
    """
    blocks = _collect_conflict_context(project_dir, branch, target)
    if not blocks:
        return None

    task_desc = (task or {}).get("description") or ""
    prompt = _build_prompt(branch, target, task_desc, blocks)

    try:
        proposal_text = _run_advisor_agent_blocking(prompt, model=model)
    except Exception:
        logger.exception("Conflict advisor agent call failed for %s", branch)
        return None

    if not proposal_text:
        return None

    proposal_path = worktree_path / "CONFLICT_PROPOSAL.md"
    try:
        worktree_path.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(proposal_text)
    except OSError:
        logger.exception(
            "Could not write conflict proposal to %s", proposal_path,
        )
        return None
    return proposal_path


__all__ = [
    "draft_conflict_proposal",
]
