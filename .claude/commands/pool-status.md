# Pool Status

Show current provider pool status: health, RPM usage, cost, and recent request routing.

## Instructions

### Step 1: Query the pool status endpoint

```bash
# If state service is running with pool health
curl -s http://localhost:8420/pool/status | python3 -m json.tool

# Or use the CLI
claw-forge pool-status --config claw-forge.yaml
```

### Step 2: Parse and display provider health

For each provider, show:
- **Status**: healthy 🟢 / degraded 🟡 / circuit-open 🔴
- **RPM**: current requests/minute vs limit
- **Success rate**: last 100 requests
- **Avg latency**: ms
- **Cost today**: USD

### Step 3: Format the output table

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Provider Pool Status — claw-forge
  Updated: 2025-05-14 10:23:45
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Provider           Status    RPM      Success  Latency  Cost Today
  ─────────────────────────────────────────────────────────────────
  claude-oauth       🟢 OK     12/∞     100%     1.2s     $0.00
  anthropic-direct   🟢 OK     45/60    99.5%    0.8s     $1.23
  groq-backup        🟡 SLOW   8/30     97%      3.4s     $0.00
  bedrock-us-east    🔴 OPEN   0/100    0%       —        $0.00

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Total cost today: $1.23
  Active sessions: 3
  Requests in last hour: 65

  Last 5 requests:
    10:23:40 → claude-oauth      [coding]    ✅ 1.1s  $0.02
    10:22:15 → anthropic-direct  [testing]   ✅ 0.9s  $0.01
    10:20:55 → anthropic-direct  [coding]    ✅ 0.8s  $0.03
    10:19:30 → groq-backup       [review]    ✅ 3.2s  $0.00
    10:18:00 → anthropic-direct  [coding]    ❌ 1.2s  $0.01

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Circuit breaker events (last 1h):
    10:15:00 — bedrock-us-east: OPEN (5 consecutive failures)
```

### Step 4: Alerts

Highlight any issues:
- 🔴 Circuit breakers open: reduced redundancy
- 🟡 Provider approaching RPM limit: may cause slowdowns
- 💰 Cost spike: more than 2x average hourly spend

### Step 5: Recommendations

Based on the status, suggest actions:
- "Consider adding a provider — only 2 of 4 are healthy"
- "groq-backup latency is high — may want to lower its priority"
- "bedrock circuit breaker will auto-reset in ~2 minutes"

### CLI shortcut

This is the same data shown by `claw-forge pool-status`. Use this slash command when you want analysis and recommendations, not just raw data.
