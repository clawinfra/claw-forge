"""Tests for claw_forge.agent.rate_limit."""
from __future__ import annotations

import pytest

from claw_forge.agent.rate_limit import (
    calculate_error_backoff,
    calculate_rate_limit_backoff,
    clamp_retry_delay,
    is_rate_limit_error,
    parse_retry_after,
)


class TestIsRateLimitError:
    def test_detects_rate_limit_phrase(self):
        assert is_rate_limit_error("You have hit the rate limit") is True

    def test_detects_too_many_requests(self):
        assert is_rate_limit_error("Too many requests, please slow down") is True

    def test_detects_429_status(self):
        assert is_rate_limit_error("HTTP 429 error received") is True

    def test_detects_quota_exceeded(self):
        assert is_rate_limit_error("quota exceeded for your account") is True

    def test_detects_capacity_exceeded(self):
        assert is_rate_limit_error("capacity exceeded on this endpoint") is True

    def test_detects_overloaded(self):
        assert is_rate_limit_error("The service is overloaded") is True

    def test_detects_529_status(self):
        assert is_rate_limit_error("Error 529: service unavailable") is True

    def test_case_insensitive(self):
        assert is_rate_limit_error("RATE LIMIT EXCEEDED") is True

    def test_non_rate_limit_error_returns_false(self):
        assert is_rate_limit_error("Invalid API key provided") is False

    def test_empty_string_returns_false(self):
        assert is_rate_limit_error("") is False

    def test_generic_server_error_returns_false(self):
        assert is_rate_limit_error("Internal server error 500") is False

    def test_ratelimit_no_space(self):
        assert is_rate_limit_error("ratelimit reached") is True


class TestParseRetryAfter:
    def test_parses_retry_after_with_colon(self):
        result = parse_retry_after("Retry-After: 30")
        assert result == 30

    def test_parses_retry_after_with_space(self):
        result = parse_retry_after("retry after 60 seconds")
        assert result == 60

    def test_parses_seconds_standalone(self):
        result = parse_retry_after("Please wait 45 seconds before retrying")
        assert result == 45

    def test_returns_none_when_no_number(self):
        result = parse_retry_after("rate limit hit, try again later")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = parse_retry_after("")
        assert result is None

    def test_prefers_retry_after_over_seconds(self):
        # "Retry-After: 30" should win over any "30 seconds" mention
        result = parse_retry_after("Retry-After: 30 — wait 30 seconds")
        assert result == 30


class TestClampRetryDelay:
    def test_clamps_below_minimum(self):
        assert clamp_retry_delay(1) == 5

    def test_clamps_above_maximum(self):
        assert clamp_retry_delay(9999) == 3600

    def test_within_range_unchanged(self):
        assert clamp_retry_delay(60) == 60

    def test_custom_bounds(self):
        assert clamp_retry_delay(100, min_s=10, max_s=200) == 100
        assert clamp_retry_delay(5, min_s=10, max_s=200) == 10
        assert clamp_retry_delay(500, min_s=10, max_s=200) == 200


class TestCalculateRateLimitBackoff:
    def test_attempt_0_is_base_plus_jitter(self):
        result = calculate_rate_limit_backoff(0, base=60.0, max_s=900.0)
        # 60 * 2^0 = 60, plus up to 10 jitter → between 60 and 70
        assert 60 <= result <= 70

    def test_attempt_1_doubles(self):
        result = calculate_rate_limit_backoff(1, base=60.0, max_s=900.0)
        # 60 * 2^1 = 120 + jitter → between 120 and 130
        assert 120 <= result <= 130

    def test_capped_at_max(self):
        result = calculate_rate_limit_backoff(10, base=60.0, max_s=900.0)
        assert result == 900

    def test_returns_int(self):
        result = calculate_rate_limit_backoff(0)
        assert isinstance(result, int)


class TestCalculateErrorBackoff:
    def test_attempt_0_returns_zero(self):
        assert calculate_error_backoff(0) == 0

    def test_attempt_1_returns_base(self):
        assert calculate_error_backoff(1, base=5.0) == 5

    def test_attempt_3(self):
        assert calculate_error_backoff(3, base=5.0) == 15

    def test_capped_at_max(self):
        assert calculate_error_backoff(1000, base=5.0, max_s=300.0) == 300

    def test_returns_int(self):
        result = calculate_error_backoff(2)
        assert isinstance(result, int)
