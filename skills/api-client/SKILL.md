# API Client

## When to use this skill
Use when making HTTP API calls, integrating REST/GraphQL endpoints, or handling auth/pagination/rate-limits.

## Protocol
1. Check for an existing SDK or client library before writing raw requests.
2. Use `httpx` (async) or `requests` (sync) — never `urllib`.
3. Always set a timeout: `httpx.get(url, timeout=10.0)`.
4. Handle status codes explicitly:
   - 200/201 → success, parse response
   - 4xx → client error, do NOT retry; surface the error
   - 429 → rate-limited; wait `Retry-After` seconds then retry once
   - 5xx → server error; retry with exponential backoff (max 3 attempts)
5. Parse JSON with `.json()`. Validate with a pydantic model when the schema is known.
6. Never hardcode auth tokens — read from env vars (`os.getenv("API_KEY")`).
7. Log request URL + status at DEBUG level. Never log auth headers.

## Commands
```bash
# Test endpoint reachability
curl -s -o /dev/null -w "%{http_code}" <url>

# Inspect response schema
curl -s <url> | python3 -m json.tool | head -50

# Test with bearer auth
curl -s -H "Authorization: Bearer $TOKEN" <url> | python3 -m json.tool
```

## Output interpretation
- HTTP 200/201 with JSON body → success; validate shape matches expected schema
- HTTP 401/403 → auth problem; check env var is set and token hasn't expired
- HTTP 429 with `Retry-After` header → wait that many seconds, then retry
- HTTP 500/502/503 → server issue; retry up to 3× with backoff (1s, 2s, 4s)
- `ConnectionError` / timeout → network issue; check URL and connectivity

Common patterns:
- Bearer auth: `headers={"Authorization": f"Bearer {token}"}`
- Pagination: check `next_cursor` / `next_page` in response; loop until absent
- Rate limit: respect `X-RateLimit-Remaining`; pause when it hits 0

## Done criteria
- All endpoints respond with expected status codes in the test suite
- No auth tokens in source code or logs
- Timeout is set on every request
- Retry logic handles 5xx without crashing
