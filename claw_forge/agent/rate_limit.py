"""Rate limit detection and backoff utilities."""
from __future__ import annotations

import math
import random
import re

RATE_LIMIT_PATTERNS = [
    r"rate.?limit",
    r"too many requests",
    r"429",
    r"quota exceeded",
    r"capacity exceeded",
    r"overloaded",
    r"529",
]


def is_rate_limit_error(text: str) -> bool:
    """Check if an error message indicates a rate limit."""
    t = text.lower()
    return any(re.search(p, t) for p in RATE_LIMIT_PATTERNS)


def parse_retry_after(text: str) -> int | None:
    """Extract retry-after seconds from error text."""
    m = re.search(r"retry.?after[:\s]+(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*seconds?", text, re.I)
    if m:
        return int(m.group(1))
    return None


def clamp_retry_delay(seconds: int, min_s: int = 5, max_s: int = 3600) -> int:
    """Clamp a retry delay to reasonable bounds."""
    return max(min_s, min(max_s, seconds))


def calculate_rate_limit_backoff(
    attempt: int, base: float = 60.0, max_s: float = 900.0
) -> int:
    """Exponential backoff with jitter for rate limits."""
    delay = base * (2**attempt) + random.uniform(0, 10)
    return int(min(delay, max_s))


def calculate_error_backoff(
    attempt: int, base: float = 5.0, max_s: float = 300.0
) -> int:
    """Linear backoff for non-rate-limit errors."""
    return int(min(base * attempt, max_s))
