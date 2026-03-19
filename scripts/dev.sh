#!/usr/bin/env bash
# dev.sh — start claw-forge local dev stack (state service + Vite UI + optional agents)
#
# Usage:
#   ./scripts/dev.sh                                    # UI + state only
#   ./scripts/dev.sh --run                              # + agent orchestrator
#   ./scripts/dev.sh --project /path/to/proj --run
#   ./scripts/dev.sh --state-port 9000 --ui-port 3000
#
# All processes are killed together on Ctrl-C.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="$REPO_DIR/ui"

# ── Defaults ────────────────────────────────────────────────────────────────
PROJECT_DIR="."
STATE_PORT="${CLAW_FORGE_STATE_PORT:-8420}"
UI_PORT="${CLAW_FORGE_UI_PORT:-5173}"
RUN_AGENTS=0
OPEN_BROWSER=1

# ── Arg parsing ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project|-p)   PROJECT_DIR="$2"; shift 2 ;;
    --state-port)   STATE_PORT="$2";  shift 2 ;;
    --ui-port)      UI_PORT="$2";     shift 2 ;;
    --run)          RUN_AGENTS=1;     shift   ;;
    --no-open)      OPEN_BROWSER=0;   shift   ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

# ── Prereq checks ────────────────────────────────────────────────────────────
if [[ ! -d "$UI_DIR" ]]; then
  echo "ERROR: ui/ source directory not found at $UI_DIR" >&2
  exit 1
fi
if ! command -v node &>/dev/null; then
  echo "ERROR: Node.js not found. Install from https://nodejs.org/" >&2
  exit 1
fi

# Install npm deps if needed
if [[ ! -d "$UI_DIR/node_modules" ]]; then
  echo "Installing UI dependencies (npm install)…"
  npm install --prefix "$UI_DIR"
fi

# ── Load project .env if present ────────────────────────────────────────────
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

DB_PATH="$PROJECT_DIR/.claw-forge/state.db"
mkdir -p "$(dirname "$DB_PATH")"

echo ""
echo "  claw-forge dev (source checkout)"
echo "  UI:        http://localhost:$UI_PORT  (Vite HMR)"
echo "  State API: http://localhost:$STATE_PORT  (uvicorn --reload)"
echo "  Project:   $PROJECT_DIR"
echo "  Database:  $DB_PATH"
if [[ $RUN_AGENTS -eq 1 ]]; then
  echo "  Agents:    enabled (--run)"
else
  echo "  Agents:    disabled — pass --run to launch orchestrator"
fi
echo ""
echo "  Press Ctrl-C to stop all servers"
echo ""

# ── Process group cleanup ────────────────────────────────────────────────────
_PIDS=()

cleanup() {
  echo ""
  echo "Stopping all servers…"
  # Ask the state service to shut down gracefully first so it can checkpoint
  # the SQLite WAL file before connections close.
  curl -sf -X POST "http://127.0.0.1:${STATE_PORT}/shutdown" >/dev/null 2>&1 || true
  # Give the lifespan teardown time to run the PASSIVE WAL checkpoint and
  # dispose the engine cleanly before we send any kill signals.
  sleep 2
  for pid in "${_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "All servers stopped."
}
trap cleanup INT TERM EXIT

# ── Launch state service ─────────────────────────────────────────────────────
# Each child is launched in a subshell that ignores SIGINT (trap '' INT) so
# the terminal's Ctrl-C does NOT reach them directly.  cleanup() is the sole
# signal path — it posts /shutdown for a graceful WAL checkpoint, then sends
# SIGTERM to each PID.  Without this, children receive SIGINT and SIGTERM
# simultaneously, racing the lifespan teardown and corrupting the SQLite WAL.
(trap '' INT; exec env CLAW_FORGE_DB_URL="sqlite+aiosqlite:///$DB_PATH" \
  uv run --directory "$REPO_DIR" claw-forge state \
    --project "$PROJECT_DIR" \
    --port "$STATE_PORT" \
    --reload) &
_PIDS+=($!)

# ── Launch Vite dev server ────────────────────────────────────────────────────
(trap '' INT; exec env VITE_API_PORT="$STATE_PORT" VITE_WS_PORT="$STATE_PORT" \
  npm run dev --prefix "$UI_DIR" -- --port "$UI_PORT" --host) &
_PIDS+=($!)

# ── Optionally launch agent orchestrator ─────────────────────────────────────
if [[ $RUN_AGENTS -eq 1 ]]; then
  sleep 2  # give state service time to bind
  (trap '' INT; exec env CLAW_FORGE_STATE_PORT="$STATE_PORT" \
    uv run --directory "$REPO_DIR" claw-forge run \
      --project "$PROJECT_DIR") &
  _PIDS+=($!)
fi

# ── Open browser ─────────────────────────────────────────────────────────────
if [[ $OPEN_BROWSER -eq 1 ]]; then
  (sleep 3 && open "http://localhost:$UI_PORT") &
fi

# ── Wait ─────────────────────────────────────────────────────────────────────
wait "${_PIDS[0]}"  # exit when state service exits
