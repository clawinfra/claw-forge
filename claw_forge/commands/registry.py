"""Command registry for claw-forge Kanban UI command palette."""

from __future__ import annotations

from typing import Any

COMMANDS: list[dict[str, Any]] = [
    {
        "id": "create-spec",
        "label": "Create Spec",
        "icon": "FileText",
        "description": "Interactive spec creation — auto-detects greenfield vs brownfield",
        "category": "setup",
        "shortcut": None,
        "args": [],
    },
    {
        "id": "expand-project",
        "label": "Expand Project",
        "icon": "Plus",
        "description": "Add new features to the current project",
        "category": "build",
        "shortcut": None,
        "args": [],
    },
    {
        "id": "check-code",
        "label": "Check Code",
        "icon": "CheckCircle",
        "description": "Run ruff + mypy + pytest and report quality",
        "category": "quality",
        "shortcut": "shift+c",
        "args": [],
    },
    {
        "id": "checkpoint",
        "label": "Checkpoint",
        "icon": "Save",
        "description": "Commit + DB snapshot + session summary",
        "category": "save",
        "shortcut": "shift+s",
        "args": [],
    },
    {
        "id": "review-pr",
        "label": "Review PR",
        "icon": "GitPullRequest",
        "description": "Structured PR review with verdict",
        "category": "quality",
        "shortcut": None,
        "args": [{"name": "pr_number", "label": "PR Number", "type": "number", "optional": True}],
    },
    {
        "id": "pool-status",
        "label": "Pool Status",
        "icon": "Activity",
        "description": "Provider health, RPM usage and cost",
        "category": "monitoring",
        "shortcut": "shift+p",
        "args": [],
    },
    {
        "id": "create-bug-report",
        "label": "Bug Report",
        "icon": "Bug",
        "description": "Guided bug report creation → runs fix",
        "category": "fix",
        "shortcut": None,
        "args": [{"name": "feature_id", "label": "Feature ID", "type": "number", "optional": True}],
    },
]

# Map command id → shell command for execution
COMMAND_SHELLS: dict[str, list[str]] = {
    "check-code": ["uv", "run", "ruff", "check", "."],
    "checkpoint": ["git", "add", "-A"],
    "pool-status": ["echo", "Pool status: checking providers..."],
    "create-spec": [
        "echo",
        "Run /create-spec in Claude Code in your project directory.",
    ],
    "expand-project": [
        "echo",
        "Run /expand-project in Claude Code in your project directory.",
    ],
    "review-pr": [
        "echo",
        "Run /review-pr in Claude Code in your project directory.",
    ],
    "create-bug-report": [
        "echo",
        "Run /create-bug-report in Claude Code in your project directory.",
    ],
}

COMMAND_IDS: set[str] = {cmd["id"] for cmd in COMMANDS}
