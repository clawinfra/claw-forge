"""Bash command security for claw-forge agents — hierarchical allowlist."""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

from claude_agent_sdk.types import HookContext, HookInput, SyncHookJSONOutput

_log = logging.getLogger("claw_forge.security")

# Commands NEVER allowed regardless of config
HARDCODED_BLOCKLIST = {
    "dd", "sudo", "su", "shutdown", "reboot", "halt", "poweroff",
    "mkfs", "fdisk", "parted", "wipefs", "shred",
    "iptables", "ip6tables", "nftables",
    "curl --upload-file", "wget --post-file",
    "nc", "netcat", "ncat",
    "ssh-keygen", "gpg --export-secret",
}

# Default allowed commands (project + claw-forge standard)
DEFAULT_ALLOWLIST = [
    "git", "npm", "npx", "node", "python", "python3", "uv", "pip",
    "pytest", "ruff", "mypy", "cargo", "rustc", "go", "make",
    "curl", "wget", "cat", "ls", "find", "grep", "awk", "sed",
    "mkdir", "cp", "mv", "rm", "echo", "touch", "chmod",
    "tar", "unzip", "zip", "gzip",
    "docker", "docker-compose",
    "playwright", "playwright-cli",
]


def _extract_command_name(bash_input: str) -> str:
    """Extract the base command name from a bash invocation."""
    cmd = bash_input.strip().split()[0] if bash_input.strip() else ""
    return Path(cmd).name  # handles ./scripts/build.sh → build.sh


def _is_allowed(cmd_name: str, allowlist: list[str]) -> bool:
    """Check if a command name matches any pattern in the allowlist."""
    return any(fnmatch.fnmatch(cmd_name, pattern) for pattern in allowlist)


def _is_blocked(cmd_name: str) -> bool:
    """Check if a command name is in the hardcoded blocklist."""
    return cmd_name in HARDCODED_BLOCKLIST


async def bash_security_hook(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """Validate bash commands against the allowlist before execution."""
    raw_cmd = input_data.get("command", "") if isinstance(input_data, dict) else str(input_data)
    cmd_name = _extract_command_name(str(raw_cmd))

    # Hardcoded blocklist — never allowed
    if _is_blocked(cmd_name):
        reason = (
            f"[Security] BLOCKED '{cmd_name}' (hardcoded)"
            f" — command: {raw_cmd[:200]}"
        )
        _log.warning(reason)
        return SyncHookJSONOutput(hookSpecificOutput={  # type: ignore[typeddict-item]
            "decision": "block",
            "reason": reason,
        })

    # Project-specific allowlist (from context if provided)
    raw = context.get("project_allowlist", []) if context else []
    project_allowlist: list[str] = list(raw) if isinstance(raw, list) else []
    full_allowlist = DEFAULT_ALLOWLIST + project_allowlist

    if not _is_allowed(cmd_name, full_allowlist):
        reason = (
            f"[Security] BLOCKED '{cmd_name}'"
            f" (not in allowlist) — command: {raw_cmd[:200]}"
        )
        _log.warning(reason)
        return SyncHookJSONOutput(hookSpecificOutput={  # type: ignore[typeddict-item]
            "decision": "block",
            "reason": reason,
        })

    _log.debug("[Security] Allowed: %s", cmd_name)
    return SyncHookJSONOutput(hookSpecificOutput={"decision": "approve"})  # type: ignore[typeddict-item]
