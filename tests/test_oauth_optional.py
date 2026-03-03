"""Tests for graceful OAuth fallback behaviour.

Covers:
- get_oauth_token_optional(): always returns None rather than raising
- anthropic_oauth provider gracefully falls back to api_key when credentials
  file is missing or malformed
- anthropic_oauth raises a clear error when neither credentials nor api_key
  are available
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claw_forge.pool.providers.base import ProviderConfig, ProviderType
from claw_forge.pool.providers.oauth import get_oauth_token_optional

# ---------------------------------------------------------------------------
# get_oauth_token_optional
# ---------------------------------------------------------------------------


class TestGetOauthTokenOptional:
    def test_returns_token_when_file_exists(self, tmp_path: Path) -> None:
        cred = tmp_path / ".credentials.json"
        cred.write_text(json.dumps({"accessToken": "tok-abc"}))

        token = get_oauth_token_optional(extra_paths=[cred])
        assert token == "tok-abc"

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "not_here.json"
        # Patch standard paths so the real ~/.claude/.credentials.json is not used
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = get_oauth_token_optional(extra_paths=[missing])
        assert token is None

    def test_returns_none_when_json_malformed(self, tmp_path: Path) -> None:
        bad = tmp_path / ".credentials.json"
        bad.write_text("{ this is not valid json }")
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = get_oauth_token_optional(extra_paths=[bad])
        assert token is None

    def test_returns_none_when_token_field_absent(self, tmp_path: Path) -> None:
        cred = tmp_path / ".credentials.json"
        cred.write_text(json.dumps({"expiresAt": "2099-01-01T00:00:00Z"}))
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = get_oauth_token_optional(extra_paths=[cred])
        assert token is None

    def test_returns_none_when_token_is_empty_string(self, tmp_path: Path) -> None:
        cred = tmp_path / ".credentials.json"
        cred.write_text(json.dumps({"accessToken": ""}))
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = get_oauth_token_optional(extra_paths=[cred])
        assert token is None

    def test_reads_nested_claudeAiOauth_format(self, tmp_path: Path) -> None:
        """Current Claude CLI (v1.x+) stores token nested under claudeAiOauth key."""
        cred = tmp_path / ".credentials.json"
        cred.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-nested-token",
                "refreshToken": "refresh-xyz",
                "expiresAt": "2099-01-01T00:00:00Z",
            },
            "organizationUuid": "org-123",
        }))
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = get_oauth_token_optional(extra_paths=[cred])
        assert token == "sk-ant-oat01-nested-token"

    def test_never_raises(self) -> None:
        """get_oauth_token_optional must never raise, even on unexpected errors."""
        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            side_effect=RuntimeError("Disk on fire"),
        ):
            token = get_oauth_token_optional()
        assert token is None

    def test_no_args_uses_standard_paths(self) -> None:
        """Calling with no args should not raise (even if no creds on disk)."""
        # We patch standard paths to point nowhere so CI doesn't accidentally
        # pick up a real credentials file.
        with patch(
            "claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS",
            [Path("/tmp/__no_creds_for_test__/.credentials.json")],
        ):
            token = get_oauth_token_optional()
        assert token is None


# ---------------------------------------------------------------------------
# Registry: anthropic_oauth — graceful fallback when file missing
# ---------------------------------------------------------------------------


class TestAnthropicOauthFallback:
    def test_falls_back_to_api_key_when_credentials_file_missing(self) -> None:
        """When OAuth creds are absent but api_key is present, no error raised."""
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.registry import create_provider

        cfg = ProviderConfig(
            name="oauth-fallback",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            api_key="sk-ant-fallback-key",
        )

        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value=None,
        ):
            provider = create_provider(cfg)

        assert isinstance(provider, AnthropicProvider)
        # Should use api_key auth (x-api-key header), not Bearer
        headers = dict(provider._client.headers)
        assert headers.get("x-api-key") == "sk-ant-fallback-key"
        assert "authorization" not in headers

    def test_falls_back_to_api_key_when_json_malformed(self, tmp_path: Path) -> None:
        """When the credentials file has bad JSON, gracefully use api_key."""
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.registry import create_provider

        bad_cred = tmp_path / ".credentials.json"
        bad_cred.write_text("not json at all {{{")

        cfg = ProviderConfig(
            name="oauth-malformed",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            api_key="sk-ant-from-config",
        )

        # Patch read_claude_oauth_token to simulate malformed JSON returning None
        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value=None,
        ):
            provider = create_provider(cfg)

        assert isinstance(provider, AnthropicProvider)
        headers = dict(provider._client.headers)
        assert headers.get("x-api-key") == "sk-ant-from-config"

    def test_raises_clear_error_when_no_oauth_and_no_api_key(self) -> None:
        """Without credentials file AND without api_key, raise a helpful error."""
        from claw_forge.pool.providers.registry import create_provider

        cfg = ProviderConfig(
            name="oauth-no-auth",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            # no api_key, no oauth_token
        )

        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value=None,
        ), pytest.raises(ValueError) as exc_info:
            create_provider(cfg)

        msg = str(exc_info.value)
        assert "anthropic_oauth" in msg
        assert "api_key" in msg

    def test_uses_oauth_token_when_available_despite_api_key(self) -> None:
        """OAuth token takes priority over api_key even in anthropic_oauth path."""
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.registry import create_provider

        cfg = ProviderConfig(
            name="oauth-priority",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            api_key="sk-ant-should-be-ignored",
        )

        with patch(  # noqa: SIM117
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value="tok-oauth-wins",
        ):
            # Also patch get_oauth_token_optional to return the token
            with patch(
                "claw_forge.pool.providers.oauth.get_oauth_token_optional",
                return_value="tok-oauth-wins",
            ):
                provider = create_provider(cfg)

        assert isinstance(provider, AnthropicProvider)
        headers = dict(provider._client.headers)
        assert headers.get("authorization") == "Bearer tok-oauth-wins"
        assert "x-api-key" not in headers

    def test_explicit_oauth_token_on_config_still_works(self) -> None:
        """If oauth_token is set directly on config, it always takes priority."""
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="explicit-oauth",
            provider_type=ProviderType.ANTHROPIC,
            oauth_token="tok-explicit",
        )
        provider = AnthropicProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("authorization") == "Bearer tok-explicit"


# ---------------------------------------------------------------------------
# ProviderConfig: oauth fields default to None
# ---------------------------------------------------------------------------


class TestProviderConfigOauthDefaults:
    def test_oauth_token_defaults_to_none(self) -> None:
        cfg = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-test",
        )
        assert cfg.oauth_token is None

    def test_oauth_token_file_defaults_to_none(self) -> None:
        cfg = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-test",
        )
        assert cfg.oauth_token_file is None

    def test_oauth_token_can_be_set(self) -> None:
        cfg = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            oauth_token="tok-xyz",
        )
        assert cfg.oauth_token == "tok-xyz"

    def test_oauth_token_file_can_be_set(self) -> None:
        cfg = ProviderConfig(
            name="test",
            provider_type=ProviderType.ANTHROPIC,
            oauth_token_file="/path/to/token",
        )
        assert cfg.oauth_token_file == "/path/to/token"
