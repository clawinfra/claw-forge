"""Tests for Claude CLI OAuth token reading and provider config generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claw_forge.pool.providers.base import ProviderConfig, ProviderType
from claw_forge.pool.providers.oauth import (
    CLAUDE_CREDENTIALS_PATHS,
    get_oauth_provider_config,
    read_claude_oauth_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_creds(tmp_path: Path, data: dict[str, Any]) -> Path:
    """Write a credentials JSON file and return its path."""
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# read_claude_oauth_token
# ---------------------------------------------------------------------------


class TestReadClaudeOauthToken:
    def test_reads_access_token_camel_case(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-abc123"})
        token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token == "tok-abc123"

    def test_reads_access_token_snake_case(self, tmp_path: Path) -> None:
        """Older Claude CLI versions use snake_case."""
        cred_path = _write_creds(tmp_path, {"access_token": "tok-snake"})
        token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token == "tok-snake"

    def test_camel_takes_priority_over_snake(self, tmp_path: Path) -> None:
        cred_path = _write_creds(
            tmp_path,
            {"accessToken": "tok-camel", "access_token": "tok-snake"},
        )
        token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token == "tok-camel"

    def test_reads_nested_claudeAiOauth_format(self, tmp_path: Path) -> None:
        """Current Claude CLI (v1.x+) nests the token under claudeAiOauth key."""
        cred_path = _write_creds(tmp_path, {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-nested",
                "refreshToken": "refresh-xyz",
                "expiresAt": "2099-01-01T00:00:00Z",
            },
            "organizationUuid": "org-123",
        })
        token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token == "sk-ant-oat01-nested"

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist.json"
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = read_claude_oauth_token(extra_paths=[nonexistent])
        assert token is None

    def test_returns_none_when_json_malformed(self, tmp_path: Path) -> None:
        p = tmp_path / ".credentials.json"
        p.write_text("{ this is not valid json }")
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = read_claude_oauth_token(extra_paths=[p])
        assert token is None

    def test_returns_none_when_token_field_missing(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"expiresAt": "2099-01-01T00:00:00Z"})
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token is None

    def test_returns_none_when_token_is_empty_string(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": ""})
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = read_claude_oauth_token(extra_paths=[cred_path])
        assert token is None

    def test_returns_none_when_no_standard_paths_exist(self) -> None:
        """When no standard credential paths exist, returns None gracefully."""
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            token = read_claude_oauth_token(
                extra_paths=[Path("/tmp/__no_such_path_xyz__/.credentials.json")]
            )
        assert token is None

    def test_extra_paths_checked_before_standard_paths(self, tmp_path: Path) -> None:
        """Extra paths take priority over the standard ones."""
        extra = tmp_path / "extra.json"
        extra.write_text(json.dumps({"accessToken": "tok-extra"}))

        # Patch standard paths to contain a different token
        with patch(
            "claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS",
            [tmp_path / "standard.json"],
        ):
            (tmp_path / "standard.json").write_text(
                json.dumps({"accessToken": "tok-standard"})
            )
            token = read_claude_oauth_token(extra_paths=[extra])

        assert token == "tok-extra"

    def test_falls_through_to_next_path_on_bad_json(self, tmp_path: Path) -> None:
        """If first path has bad JSON, the next valid path should be used."""
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        good = tmp_path / "good.json"
        good.write_text(json.dumps({"accessToken": "tok-good"}))

        token = read_claude_oauth_token(extra_paths=[bad, good])
        assert token == "tok-good"

    def test_standard_paths_list_is_non_empty(self) -> None:
        """Sanity check — the module exports at least 2 standard paths."""
        assert len(CLAUDE_CREDENTIALS_PATHS) >= 2


# ---------------------------------------------------------------------------
# get_oauth_provider_config
# ---------------------------------------------------------------------------


class TestGetOauthProviderConfig:
    def test_returns_provider_config_when_token_found(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-oauth"})
        cfg = get_oauth_provider_config(extra_paths=[cred_path])

        assert cfg is not None
        assert isinstance(cfg, ProviderConfig)

    def test_config_has_oauth_token_set(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-oauth"})
        cfg = get_oauth_provider_config(extra_paths=[cred_path])
        assert cfg is not None
        assert cfg.oauth_token == "tok-oauth"

    def test_config_provider_type_is_anthropic(self, tmp_path: Path) -> None:
        """OAuth config should delegate to the standard AnthropicProvider."""
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-oauth"})
        cfg = get_oauth_provider_config(extra_paths=[cred_path])
        assert cfg is not None
        assert cfg.provider_type == ProviderType.ANTHROPIC

    def test_default_name_is_claude_oauth(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-oauth"})
        cfg = get_oauth_provider_config(extra_paths=[cred_path])
        assert cfg is not None
        assert cfg.name == "claude-oauth"

    def test_custom_name_and_priority(self, tmp_path: Path) -> None:
        cred_path = _write_creds(tmp_path, {"accessToken": "tok-oauth"})
        cfg = get_oauth_provider_config(
            name="my-oauth", priority=5, extra_paths=[cred_path]
        )
        assert cfg is not None
        assert cfg.name == "my-oauth"
        assert cfg.priority == 5

    def test_returns_none_when_no_token_found(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "missing.json"
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            cfg = get_oauth_provider_config(extra_paths=[nonexistent])
        assert cfg is None


# ---------------------------------------------------------------------------
# AnthropicProvider — OAuth Bearer token usage
# ---------------------------------------------------------------------------


class TestAnthropicProviderOauthIntegration:
    """Verify that AnthropicProvider uses Bearer when oauth_token is set."""

    def test_uses_bearer_when_oauth_token_set(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="oauth-test",
            provider_type=ProviderType.ANTHROPIC,
            oauth_token="tok-bearer",
        )
        provider = AnthropicProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("authorization") == "Bearer tok-bearer"
        assert "x-api-key" not in headers

    def test_uses_x_api_key_when_no_oauth_token(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="apikey-test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-key-123",
        )
        provider = AnthropicProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("x-api-key") == "sk-key-123"
        assert "authorization" not in headers

    def test_oauth_token_takes_priority_over_api_key(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="both-test",
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-key-ignored",
            oauth_token="tok-priority",
        )
        provider = AnthropicProvider(cfg)
        headers = dict(provider._client.headers)
        assert headers.get("authorization") == "Bearer tok-priority"
        assert "x-api-key" not in headers

    def test_raises_when_no_auth_provided(self) -> None:
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType

        cfg = ProviderConfig(
            name="no-auth",
            provider_type=ProviderType.ANTHROPIC,
        )
        with pytest.raises(ValueError, match="requires api_key"):
            AnthropicProvider(cfg)


# ---------------------------------------------------------------------------
# Registry — anthropic_oauth auto-injection
# ---------------------------------------------------------------------------


class TestRegistryAnthropicOauth:
    def test_anthropic_oauth_injects_token_into_config(self, tmp_path: Path) -> None:
        from claw_forge.pool.providers.registry import create_provider

        cred_path = tmp_path / ".credentials.json"
        cred_path.write_text(json.dumps({"accessToken": "tok-injected"}))

        cfg = ProviderConfig(
            name="oauth-auto",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
        )

        # Patch at the oauth module level — registry calls _oauth_mod.read_claude_oauth_token()
        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value="tok-injected",
        ):
            provider = create_provider(cfg)

        # The created provider should be AnthropicProvider with Bearer auth
        from claw_forge.pool.providers.anthropic import AnthropicProvider
        assert isinstance(provider, AnthropicProvider)
        headers = dict(provider._client.headers)
        assert headers.get("authorization") == "Bearer tok-injected"

    def test_anthropic_oauth_raises_when_no_token(self) -> None:
        from claw_forge.pool.providers.registry import create_provider

        cfg = ProviderConfig(
            name="oauth-missing",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
        )

        # Patch at the oauth module level
        with patch(
            "claw_forge.pool.providers.oauth.read_claude_oauth_token",
            return_value=None,
        ), pytest.raises(ValueError, match="no OAuth credentials"):
            create_provider(cfg)


# ---------------------------------------------------------------------------
# create_providers_from_configs — traceback-free oauth skip
# ---------------------------------------------------------------------------


class TestCreateProvidersFromConfigsOauthSkip:
    """Regression: oauth provider with no credentials must NOT print a traceback."""

    def test_oauth_provider_skipped_silently_no_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When claude-oauth has no credentials and no api_key, it must be
        silently skipped (DEBUG log only) — no traceback, no WARNING on stderr."""
        from claw_forge.pool.providers.base import ProviderConfig, ProviderType
        from claw_forge.pool.providers.registry import create_providers_from_configs

        oauth_cfg = ProviderConfig(
            name="claude-oauth",
            provider_type=ProviderType.ANTHROPIC_OAUTH,
            priority=1,
        )
        # Patch out both standard and extra credential paths so no token is found
        with patch("claw_forge.pool.providers.oauth.CLAUDE_CREDENTIALS_PATHS", []):
            providers = create_providers_from_configs([oauth_cfg])

        # Provider must be skipped (not instantiated)
        assert len(providers) == 0

        # No traceback must appear on stderr
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "ValueError" not in captured.err
        assert "Failed to create provider" not in captured.err

    def test_non_oauth_provider_config_error_warns_no_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A non-oauth provider that raises ValueError on init should log a
        WARNING (no traceback) — not crash the whole pool."""
        from unittest.mock import patch

        from claw_forge.pool.providers.base import ProviderConfig, ProviderType
        from claw_forge.pool.providers.registry import create_providers_from_configs

        bad_cfg = ProviderConfig(
            name="bad-provider",
            provider_type=ProviderType.ANTHROPIC,
            priority=1,
            api_key="",  # empty key will cause ValueError in AnthropicProvider
        )
        with patch(
            "claw_forge.pool.providers.registry.create_provider",
            side_effect=ValueError("missing api_key"),
        ):
            providers = create_providers_from_configs([bad_cfg])

        assert len(providers) == 0
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "ValueError" not in captured.err  # no raw exception output
