# Security Audit

## When to use this skill
Use when auditing a codebase for vulnerabilities, reviewing dependencies, or checking for exposed secrets.

## Protocol
Run all steps in order — do not skip any:

1. **Dependency audit** — check for known CVEs in dependencies:
   - Python: `pip-audit`
   - Node: `npm audit`
   - Rust: `cargo audit`
   - Go: `go list -m all | nancy sleuth`

2. **Secret scan** — find credentials accidentally committed:
   - Check git history: `git log --all --full-history -- "*.env" "*.key"`
   - Scan source: `grep -r "sk-\|Bearer\|password\s*=\|api_key\s*=" --include="*.py" .`
   - Use trufflehog for deep scan: `trufflehog filesystem .`

3. **Static analysis** — automated vulnerability detection:
   - Python: `bandit -r . -ll`
   - All languages: `semgrep --config=auto .`

4. **Input validation review** — manually check every user-controlled input:
   - Does it reach a SQL query? → must be parameterized
   - Does it reach a shell command? → must be rejected or sanitized
   - Does it reach the filesystem? → resolve path and verify it stays under allowed root
   - Does it get rendered as HTML? → must be escaped

5. **Auth review** — check authentication and authorization:
   - Tokens: do they expire? Are scopes minimal?
   - Storage: no sensitive tokens in localStorage, logs, or URLs
   - Endpoints: are all sensitive endpoints protected? Test with no/expired token.

## Commands
```bash
# Python dependency audit
pip-audit --format json | python3 -m json.tool

# Python static analysis
bandit -r . -ll -f json | python3 -m json.tool

# Secret scan (deep)
trufflehog filesystem .

# Semgrep (multi-language)
semgrep --config=auto .

# Node dependency audit
npm audit --json | python3 -m json.tool

# Git history secret search
git log --all --full-history -- "*.env" "*.key" "*.pem"
grep -r "password\s*=\|token\s*=\|secret\s*=" --include="*.py" --include="*.js" .
```

## Output interpretation
Severity classification:

| Severity | Examples                                        | Action              |
|----------|-------------------------------------------------|---------------------|
| CRITICAL | RCE, auth bypass, mass data exfiltration        | Fix immediately     |
| HIGH     | SQLi, XSS, hardcoded secret, privilege escalation | Fix before merge  |
| MEDIUM   | Missing input validation, insecure defaults     | Fix this sprint     |
| LOW      | Verbose error messages, weak but non-critical   | Track in backlog    |

- `bandit` severity HIGH + confidence HIGH → treat as HIGH finding
- `pip-audit` CVE with CVSS ≥ 9.0 → CRITICAL; upgrade dependency immediately
- Secret found in git history → must be rotated; the secret is compromised even after removal

## Done criteria
- All CRITICAL and HIGH findings are fixed
- `pip-audit` / `npm audit` shows no HIGH/CRITICAL CVEs
- `bandit` and `semgrep` show no HIGH severity findings
- No secrets found in source or git history
- All user-controlled inputs are validated before reaching DB/shell/filesystem
