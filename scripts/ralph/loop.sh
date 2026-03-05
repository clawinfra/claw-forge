#!/bin/bash
# Autonomous Agent Loop with Context Handoff
# Usage: ./loop.sh [max_iterations]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"  # Go up from scripts/ralph/ to project root
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
HANDOFF_FILE="$SCRIPT_DIR/handoff.json"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"
AGENT_INSTRUCTIONS="$SCRIPT_DIR/CLAUDE.md"

MAX_ITERATIONS=${1:-20}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    if ! command -v claude &> /dev/null; then
        log_error "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        log_error "jq not found. Install with: brew install jq (macOS) or apt-get install jq (Linux)"
        exit 1
    fi

    if [ ! -f "$PRD_FILE" ]; then
        log_error "prd.json not found at $PRD_FILE"
        log_info "Create one with: /autonomous-agent-loop analyze path/to/requirements.md"
        exit 1
    fi

    if [ ! -f "$AGENT_INSTRUCTIONS" ]; then
        log_error "CLAUDE.md not found at $AGENT_INSTRUCTIONS"
        exit 1
    fi
}

# Archive previous run if branch changed
archive_previous_run() {
    if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
        CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
        LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

        if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
            DATE=$(date +%Y-%m-%d)
            FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
            ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"

            log_info "Archiving previous run: $LAST_BRANCH"
            mkdir -p "$ARCHIVE_FOLDER"
            [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
            [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
            [ -f "$HANDOFF_FILE" ] && cp "$HANDOFF_FILE" "$ARCHIVE_FOLDER/"
            log_success "Archived to: $ARCHIVE_FOLDER"

            # Reset progress file for new run
            reset_progress_file
            # Clear handoff file for new run
            rm -f "$HANDOFF_FILE"
        fi
    fi
}

# Track current branch
track_branch() {
    if [ -f "$PRD_FILE" ]; then
        CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
        if [ -n "$CURRENT_BRANCH" ]; then
            echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
        fi
    fi
}

# Initialize or reset progress file
reset_progress_file() {
    cat > "$PROGRESS_FILE" << EOF
# Ralph Progress Log

## Codebase Patterns
<!-- Add reusable patterns discovered during implementation -->

---

Started: $(date)
EOF
}

# Initialize progress file if it doesn't exist
init_progress_file() {
    if [ ! -f "$PROGRESS_FILE" ]; then
        reset_progress_file
    fi
}

# Check if all stories are complete
all_stories_complete() {
    local incomplete=$(jq '[.userStories[] | select(.passes == false)] | length' "$PRD_FILE")
    [ "$incomplete" -eq 0 ]
}

# Get current story status
get_story_status() {
    echo ""
    echo "Story Status:"
    jq -r '.userStories[] | "  \(.id): \(.title) - \(if .passes then "DONE" else "PENDING" end)"' "$PRD_FILE"
    echo ""
}

# Check for handoff file and display status
check_handoff_status() {
    if [ -f "$HANDOFF_FILE" ]; then
        log_warn "Handoff file detected - continuing from previous session"
        local story_id=$(jq -r '.current_story.id // "unknown"' "$HANDOFF_FILE")
        local instruction=$(jq -r '.handoff_instruction // "No instruction"' "$HANDOFF_FILE")
        echo "  Resuming: $story_id"
        echo "  Instruction: $instruction"
        echo ""
    fi
}

# Build the prompt for Claude
build_prompt() {
    # Read the base instructions
    local base_instructions=$(cat "$AGENT_INSTRUCTIONS")

    # Add context about file locations
    local context="
IMPORTANT FILE LOCATIONS (relative to project root):
- PRD file: scripts/ralph/prd.json (or $PRD_FILE)
- Progress file: scripts/ralph/progress.txt (or $PROGRESS_FILE)
- Handoff file: scripts/ralph/handoff.json (or $HANDOFF_FILE)

Working directory: $PROJECT_DIR

$base_instructions"

    echo "$context"
}

# Main loop
main() {
    check_prerequisites
    archive_previous_run
    track_branch
    init_progress_file

    local project_name=$(jq -r '.project // "Project"' "$PRD_FILE")
    local branch_name=$(jq -r '.branchName // "ralph/feature"' "$PRD_FILE")

    echo ""
    echo "=========================================="
    echo "  Autonomous Agent Loop"
    echo "  Project: $project_name"
    echo "  Branch: $branch_name"
    echo "  Max Iterations: $MAX_ITERATIONS"
    echo "=========================================="

    get_story_status
    check_handoff_status

    for i in $(seq 1 $MAX_ITERATIONS); do
        # Check if all done before starting iteration
        if all_stories_complete; then
            log_success "All stories complete!"
            get_story_status
            exit 0
        fi

        echo ""
        echo "==========================================="
        echo "  Iteration $i of $MAX_ITERATIONS"
        echo "==========================================="

        # Create a temporary file with the full prompt
        TEMP_PROMPT=$(mktemp)
        build_prompt > "$TEMP_PROMPT"

        # Run Claude with the agent instructions from temp file
        # Use --dangerously-skip-permissions for autonomous operation
        log_info "Starting Claude instance..."

        # Change to project directory and run claude
        OUTPUT=$(cd "$PROJECT_DIR" && claude --dangerously-skip-permissions -p "$(cat "$TEMP_PROMPT")" 2>&1 | tee /dev/stderr) || true

        # Clean up temp file
        rm -f "$TEMP_PROMPT"

        # Check for completion signal
        if echo "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
            echo ""
            log_success "All tasks completed!"
            log_success "Finished at iteration $i of $MAX_ITERATIONS"
            get_story_status
            exit 0
        fi

        # Check for handoff signal
        if echo "$OUTPUT" | grep -q "<handoff>CONTEXT_THRESHOLD</handoff>"; then
            log_warn "Context threshold reached - handing off to fresh instance"
            echo "  Handoff state saved to handoff.json"
            echo "  Continuing with fresh context..."
            sleep 2
            continue
        fi

        log_info "Iteration $i complete. Continuing..."
        sleep 2
    done

    echo ""
    log_warn "Reached max iterations ($MAX_ITERATIONS) without completing all tasks."
    log_info "Check $PROGRESS_FILE for status."
    get_story_status
    exit 1
}

main "$@"
