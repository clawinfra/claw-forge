"""Smart tool permission callback — replaces hook-based security for interactive sessions.

Unlike hook-based security (which only fires PreToolUse), the can_use_tool
callback gives claw-forge programmatic control over every tool invocation with:
- Input inspection and mutation before execution
- Project-directory sandboxing for ALL file operations (read and write)
- Bash command path sandboxing
- Dangerous command blocking

Note: can_use_tool requires streaming mode — pass prompt as an AsyncIterable
when using ClaudeSDKClient directly, or use AgentSession which handles this
transparently.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

# Commands that are always blocked regardless of context
ALWAYS_BLOCK: frozenset[str] = frozenset({
    "dd",
    "sudo",
    "su",
    "shutdown",
    "reboot",
    "rm -rf /",
})

# File tools that should be sandboxed to project_dir
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit"})
READ_TOOLS: frozenset[str] = frozenset({"Read", "Glob", "Grep"})
FILE_TOOLS: frozenset[str] = WRITE_TOOLS | READ_TOOLS

# ── Bash path sandboxing constants ────────────────────────────────────────────

# Absolute paths that are safe to reference from Bash (device files, etc.)
ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr",
    "/dev/fd/", "/dev/urandom", "/dev/zero",
    "/proc/self/",
)

# Commands whose arguments should NOT be path-checked — they legitimately
# reference system paths for tool invocation, not file content access.
SANDBOX_EXEMPT_COMMANDS: frozenset[str] = frozenset({
    "git", "uv", "pip", "npm", "npx", "node", "python", "python3",
    "cargo", "rustc", "go", "make", "docker", "docker-compose",
    "pytest", "ruff", "mypy", "playwright", "playwright-cli",
})

# Regex to split compound commands on shell operators
_SHELL_SPLIT_RE = re.compile(r'\s*(?:[|&;]+|\(|\))\s*')

# Regex to extract redirection targets (e.g., > /tmp/out.txt, >> /etc/cron)
_REDIRECT_RE = re.compile(r'[012]?>>?\s*(/[^\s;|&)]+)')


# ── Bash path helpers ─────────────────────────────────────────────────────────


def _is_allowed_path(path_str: str) -> bool:
    """Check if a path is in the safe allowlist (e.g., /dev/null)."""
    return any(path_str.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def _is_in_sandbox(path_str: str, resolved_project: Path) -> bool:
    """Check if a path resolves inside the project directory."""
    try:
        Path(path_str).resolve().relative_to(resolved_project)
        return True
    except (ValueError, OSError):
        return False


def _check_bash_paths(command: str, project_dir: Path) -> str | None:
    """Check a bash command for file paths outside the sandbox.

    Splits the command on shell operators (|, &&, ;), tokenizes each
    sub-command with shlex, and validates that all path-like arguments
    resolve inside ``project_dir``.

    Dev-toolchain commands (git, python, uv, npm, etc.) are exempt since
    they legitimately reference system paths.

    Returns None if the command is safe, or a denial reason string.
    """
    resolved_project = project_dir.resolve()

    # Check redirect targets first (> /tmp/out.txt, >> /etc/cron)
    for match in _REDIRECT_RE.finditer(command):
        target = match.group(1)
        if not _is_allowed_path(target) and not _is_in_sandbox(target, resolved_project):
            return f"Bash redirect outside project dir: {target}"

    # Split into sub-commands on |, &&, ||, ;
    sub_commands = _SHELL_SPLIT_RE.split(command)

    for sub_cmd in sub_commands:
        sub_cmd = sub_cmd.strip()
        if not sub_cmd:
            continue

        # Tokenize — fall back to str.split() if shlex fails
        try:
            tokens = shlex.split(sub_cmd)
        except ValueError:
            tokens = sub_cmd.split()

        if not tokens:
            continue

        # Extract base command name (handles ./script.sh, /usr/bin/python3)
        base_cmd = Path(tokens[0]).name

        # Skip exempt commands (git, python3, uv, npm, etc.)
        if base_cmd in SANDBOX_EXEMPT_COMMANDS:
            continue

        # cd outside sandbox
        if base_cmd == "cd" and len(tokens) > 1:
            target = tokens[1]
            if target == "-":
                continue  # cd - (go to previous dir) is harmless
            if not _is_in_sandbox(target, resolved_project):
                return f"Bash cd outside project dir: {target}"
            continue

        # Check all non-flag tokens for paths outside sandbox
        for token in tokens[1:]:
            if token.startswith("-"):
                continue  # skip flags like -n, --verbose

            # Absolute paths
            if token.startswith("/"):
                if not _is_allowed_path(token) and not _is_in_sandbox(
                    token, resolved_project
                ):
                    return f"Bash path outside project dir: {token}"

            # Relative path escapes (../../etc/passwd)
            elif ".." in token:
                if not _is_in_sandbox(token, resolved_project):
                    return f"Bash path escape outside project dir: {token}"

            # curl @file syntax (@/etc/passwd)
            elif token.startswith("@/"):
                file_ref = token[1:]  # strip the @
                if not _is_allowed_path(file_ref) and not _is_in_sandbox(
                    file_ref, resolved_project
                ):
                    return f"Bash file reference outside project dir: {file_ref}"

    return None


# ── Permission callbacks ──────────────────────────────────────────────────────


async def smart_can_use_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
    project_dir: Path | None = None,
) -> PermissionResultAllow | PermissionResultDeny:
    """Programmatic permission control for Claude tool calls.

    Evaluation order:
    1. Bash tool: block any command matching ALWAYS_BLOCK patterns, then
       check all path arguments against the project_dir sandbox.
    2. File tools (Read/Write/Edit/Glob/Grep): block access outside project_dir.
    3. Everything else: allow.

    Args:
        tool_name: Name of the tool being invoked (e.g. "Bash", "Write").
        tool_input: The tool's input dict (e.g. {"command": "sudo rm -rf /"}).
        context: SDK ToolPermissionContext (may contain session metadata).
        project_dir: If provided, all file operations are sandboxed to this directory.

    Returns:
        PermissionResultAllow if the tool call should proceed.
        PermissionResultDeny with a reason if it should be blocked.
    """
    # ── Bash: block dangerous commands + sandbox paths ────────────────────
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        for blocked in ALWAYS_BLOCK:
            if blocked in cmd:
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"Blocked: {blocked}",
                )
        if project_dir is not None:
            denial = _check_bash_paths(cmd, project_dir)
            if denial:
                return PermissionResultDeny(behavior="deny", message=denial)

    # ── File tools: sandbox to project_dir ────────────────────────────────
    if tool_name in FILE_TOOLS and project_dir is not None:
        # Read/Write/Edit use "file_path"; Glob/Grep use "path"
        file_path = tool_input.get("file_path") or tool_input.get("path", "")
        if file_path:
            try:
                Path(file_path).resolve().relative_to(project_dir.resolve())
            except ValueError:
                action = "Write" if tool_name in WRITE_TOOLS else "Read"
                return PermissionResultDeny(
                    behavior="deny",
                    message=f"{action} outside project dir: {file_path}",
                )

    return PermissionResultAllow(behavior="allow")


def make_can_use_tool(
    project_dir: Path | None = None,
    extra_blocked: set[str] | None = None,
) -> Any:
    """Create a can_use_tool callback bound to a specific project directory.

    All file operations (Read, Write, Edit, Glob, Grep, MultiEdit) and Bash
    commands with path arguments are sandboxed to project_dir — agents cannot
    access files outside it.

    Args:
        project_dir: Root directory to sandbox all file operations to.
        extra_blocked: Additional Bash command patterns to block.

    Returns:
        Async callable compatible with ClaudeAgentOptions.can_use_tool.

    Example::

        from claw_forge.agent.permissions import make_can_use_tool
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(
            can_use_tool=make_can_use_tool(project_dir=Path("/my/project")),
            ...
        )
    """
    blocked = ALWAYS_BLOCK | (extra_blocked or set())

    async def _can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Bash: check expanded block list + sandbox paths
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            for pattern in blocked:
                if pattern in cmd:
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"Blocked: {pattern}",
                    )
            if project_dir is not None:
                denial = _check_bash_paths(cmd, project_dir)
                if denial:
                    return PermissionResultDeny(behavior="deny", message=denial)

        # File tools: sandbox to project_dir
        if tool_name in FILE_TOOLS and project_dir is not None:
            file_path = tool_input.get("file_path") or tool_input.get("path", "")
            if file_path:
                try:
                    Path(file_path).resolve().relative_to(project_dir.resolve())
                except ValueError:
                    action = "Write" if tool_name in WRITE_TOOLS else "Read"
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"{action} outside project dir: {file_path}",
                    )

        return PermissionResultAllow(behavior="allow")

    return _can_use_tool
