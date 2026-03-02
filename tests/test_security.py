"""Tests for claw_forge.agent.security."""
from __future__ import annotations

import pytest

from claw_forge.agent.security import (
    DEFAULT_ALLOWLIST,
    _extract_command_name,
    _is_allowed,
    _is_blocked,
    bash_security_hook,
)


class TestExtractCommandName:
    def test_simple_command(self):
        assert _extract_command_name("git status") == "git"

    def test_command_with_path(self):
        assert _extract_command_name("./scripts/build.sh") == "build.sh"

    def test_absolute_path(self):
        assert _extract_command_name("/usr/bin/python3 script.py") == "python3"

    def test_empty_string(self):
        assert _extract_command_name("") == ""

    def test_whitespace_only(self):
        assert _extract_command_name("   ") == ""

    def test_leading_whitespace(self):
        assert _extract_command_name("  npm install") == "npm"


class TestIsAllowed:
    def test_allowed_command(self):
        assert _is_allowed("git", DEFAULT_ALLOWLIST) is True

    def test_allowed_npm(self):
        assert _is_allowed("npm", DEFAULT_ALLOWLIST) is True

    def test_not_allowed(self):
        assert _is_allowed("evil-tool", DEFAULT_ALLOWLIST) is False

    def test_custom_allowlist(self):
        assert _is_allowed("custom-tool", ["custom-tool"]) is True

    def test_glob_pattern(self):
        assert _is_allowed("my-script.sh", ["*.sh"]) is True

    def test_empty_allowlist(self):
        assert _is_allowed("git", []) is False


class TestIsBlocked:
    def test_sudo_blocked(self):
        assert _is_blocked("sudo") is True

    def test_dd_blocked(self):
        assert _is_blocked("dd") is True

    def test_shutdown_blocked(self):
        assert _is_blocked("shutdown") is True

    def test_nc_blocked(self):
        assert _is_blocked("nc") is True

    def test_allowed_command_not_blocked(self):
        assert _is_blocked("git") is False

    def test_empty_string_not_blocked(self):
        assert _is_blocked("") is False


class TestBashSecurityHook:
    @pytest.mark.asyncio
    async def test_allows_git(self):
        result = await bash_security_hook({"command": "git status"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_allows_npm(self):
        result = await bash_security_hook({"command": "npm install"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_blocks_sudo(self):
        result = await bash_security_hook({"command": "sudo rm -rf /"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "block"
        assert "permanently blocked" in result["hookSpecificOutput"]["reason"]

    @pytest.mark.asyncio
    async def test_blocks_unknown_command(self):
        result = await bash_security_hook({"command": "evil-tool --destroy"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "block"
        assert "not in the allowed commands list" in result["hookSpecificOutput"]["reason"]

    @pytest.mark.asyncio
    async def test_project_allowlist_extends_defaults(self):
        context = {"project_allowlist": ["my-custom-tool"]}
        result = await bash_security_hook({"command": "my-custom-tool run"}, None, context)
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_none_context_treated_as_empty(self):
        result = await bash_security_hook({"command": "git log"}, None, None)
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_blocks_dd(self):
        result = await bash_security_hook({"command": "dd if=/dev/zero of=/dev/sda"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "block"

    @pytest.mark.asyncio
    async def test_allows_pytest(self):
        result = await bash_security_hook({"command": "pytest tests/ -v"}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_allows_ruff(self):
        result = await bash_security_hook({"command": "ruff check ."}, None, {})
        assert result["hookSpecificOutput"]["decision"] == "approve"

    @pytest.mark.asyncio
    async def test_script_path_resolves_to_name(self):
        """./scripts/deploy.sh is not in allowlist → should be blocked."""
        result = await bash_security_hook({"command": "./scripts/deploy.sh"}, None, {})
        # deploy.sh is not in DEFAULT_ALLOWLIST
        assert result["hookSpecificOutput"]["decision"] == "block"

    @pytest.mark.asyncio
    async def test_str_input_does_not_crash(self):
        """Non-dict HookInput (str) should not crash."""
        result = await bash_security_hook("git status", None, {})
        # "git" extracted from string via str() → depends on input format
        # Should not raise
        assert "decision" in result["hookSpecificOutput"]
