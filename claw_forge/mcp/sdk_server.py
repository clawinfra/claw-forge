"""In-process SDK MCP server for feature management.

Runs in-process via create_sdk_mcp_server() — zero subprocess overhead vs
AutoForge's 400ms cold start per agent session.

The feature tools here mirror the subprocess-based feature_mcp.py but execute
entirely in-process, with direct SQLAlchemy access instead of subprocess IPC.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DBSession

from claw_forge.mcp.feature_mcp import (
    Feature,
    FeatureBase,
    FeatureDependency,
    _deps_satisfied,
)

# ── DB helpers ────────────────────────────────────────────────────────────────


def _get_engine_for_dir(project_dir: Path):
    """Get (or create) a SQLAlchemy engine for the given project directory."""
    db_path = project_dir / ".claw-forge" / "features.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    FeatureBase.metadata.create_all(engine)
    return engine


# ── Tool factories ─────────────────────────────────────────────────────────────


def _make_tools(project_dir: Path) -> list:
    """Create bound tool functions for the given project_dir."""
    engine = _get_engine_for_dir(project_dir)

    @tool("feature_get_stats", "Get feature completion statistics", {})
    async def feature_get_stats(args: dict) -> dict:
        """Return counts of features per status."""
        with DBSession(engine) as session:
            all_features = session.execute(select(Feature)).scalars().all()
            stats: dict[str, Any] = {
                "total": len(all_features),
                "pending": 0,
                "in_progress": 0,
                "passing": 0,
                "failing": 0,
                "skipped": 0,
            }
            for f in all_features:
                status = f.status or "pending"
                if status in stats:
                    stats[status] += 1
        return {"content": [{"type": "text", "text": str(stats)}]}

    @tool(
        "feature_get_by_id",
        "Get a feature by its ID",
        {"type": "object", "properties": {"feature_id": {"type": "string"}}, "required": ["feature_id"]},  # noqa: E501
    )
    async def feature_get_by_id(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            result = feature.to_dict() if feature else None
        import json
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool("feature_get_ready", "Get features with all dependencies satisfied", {})
    async def feature_get_ready(args: dict) -> dict:
        with DBSession(engine) as session:
            pending = session.execute(
                select(Feature).where(Feature.status == "pending")
            ).scalars().all()
            ready = [f.to_dict() for f in pending if _deps_satisfied(session, f)]
        import json
        return {"content": [{"type": "text", "text": json.dumps(ready)}]}

    @tool(
        "feature_claim_and_get",
        "Atomically claim the next available feature for an agent",
        {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": []},
    )
    async def feature_claim_and_get(args: dict) -> dict:
        agent_id = args.get("agent_id", "")
        with DBSession(engine) as session:
            pending = session.execute(
                select(Feature).where(Feature.status == "pending")
            ).scalars().all()
            claimed = None
            for feature in pending:
                if _deps_satisfied(session, feature):
                    feature.status = "in_progress"
                    feature.claimed_by = agent_id or "unknown"
                    feature.updated_at = datetime.now(UTC)
                    session.commit()
                    session.refresh(feature)
                    claimed = feature.to_dict()
                    break
        import json
        return {"content": [{"type": "text", "text": json.dumps(claimed)}]}

    @tool(
        "feature_mark_passing",
        "Mark a feature as passing (completed successfully)",
        {"type": "object", "properties": {"feature_id": {"type": "string"}}, "required": ["feature_id"]},  # noqa: E501
    )
    async def feature_mark_passing(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            result = None
            if feature:
                feature.status = "passing"
                feature.claimed_by = None
                feature.fail_reason = None
                feature.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(feature)
                result = feature.to_dict()
        import json
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "feature_mark_failing",
        "Mark a feature as failing with an optional reason",
        {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["feature_id"],
        },
    )
    async def feature_mark_failing(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        reason = args.get("reason", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            result = None
            if feature:
                feature.status = "failing"
                feature.fail_reason = reason
                feature.claimed_by = None
                feature.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(feature)
                result = feature.to_dict()
        import json
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "feature_mark_in_progress",
        "Mark a feature as in_progress",
        {"type": "object", "properties": {"feature_id": {"type": "string"}}, "required": ["feature_id"]},  # noqa: E501
    )
    async def feature_mark_in_progress(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            result = None
            if feature:
                feature.status = "in_progress"
                feature.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(feature)
                result = feature.to_dict()
        import json
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "feature_clear_in_progress",
        "Release a claim on a feature — resets it back to pending",
        {"type": "object", "properties": {"feature_id": {"type": "string"}}, "required": ["feature_id"]},  # noqa: E501
    )
    async def feature_clear_in_progress(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            result = None
            if feature:
                feature.status = "pending"
                feature.claimed_by = None
                feature.updated_at = datetime.now(UTC)
                session.commit()
                session.refresh(feature)
                result = feature.to_dict()
        import json
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "feature_create_bulk",
        "Batch create features from a JSON list",
        {
            "type": "object",
            "properties": {
                "features_json": {"type": "string", "description": "JSON array of feature dicts"},
            },
            "required": ["features_json"],
        },
    )
    async def feature_create_bulk(args: dict) -> dict:
        import json
        features_data = json.loads(args.get("features_json", "[]"))
        created = []
        with DBSession(engine) as session:
            for item in features_data:
                feature = Feature(
                    id=str(uuid.uuid4()),
                    name=item.get("name", "Unnamed"),
                    category=item.get("category", "general"),
                    description=item.get("description", ""),
                    steps=item.get("steps", []),
                    status="pending",
                )
                session.add(feature)
                session.flush()
                created.append(feature.to_dict())
            session.commit()
        return {"content": [{"type": "text", "text": json.dumps(created)}]}

    @tool(
        "feature_create",
        "Create a single feature",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "steps_json": {"type": "string", "description": "JSON array of step strings"},
            },
            "required": ["name"],
        },
    )
    async def feature_create(args: dict) -> dict:
        import json
        steps = json.loads(args.get("steps_json", "[]"))
        with DBSession(engine) as session:
            feature = Feature(
                id=str(uuid.uuid4()),
                name=args.get("name", "Unnamed"),
                category=args.get("category", "general"),
                description=args.get("description", ""),
                steps=steps,
                status="pending",
            )
            session.add(feature)
            session.commit()
            session.refresh(feature)
            result = feature.to_dict()
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    @tool(
        "feature_add_dependency",
        "Add a dependency edge: feature_id depends on depends_on_id",
        {
            "type": "object",
            "properties": {
                "feature_id": {"type": "string"},
                "depends_on_id": {"type": "string"},
            },
            "required": ["feature_id", "depends_on_id"],
        },
    )
    async def feature_add_dependency(args: dict) -> dict:
        feature_id = args.get("feature_id", "")
        depends_on_id = args.get("depends_on_id", "")
        with DBSession(engine) as session:
            feature = session.get(Feature, feature_id)
            depends_on = session.get(Feature, depends_on_id)
            if feature is None or depends_on is None:
                success = False
            else:
                existing = [d for d in feature.dependencies if d.depends_on_id == depends_on_id]
                if not existing:
                    dep = FeatureDependency(feature_id=feature_id, depends_on_id=depends_on_id)
                    session.add(dep)
                    session.commit()
                success = True
        return {"content": [{"type": "text", "text": str(success)}]}

    return [
        feature_get_stats,
        feature_get_by_id,
        feature_get_ready,
        feature_claim_and_get,
        feature_mark_passing,
        feature_mark_failing,
        feature_mark_in_progress,
        feature_clear_in_progress,
        feature_create_bulk,
        feature_create,
        feature_add_dependency,
    ]


# ── Public factory ─────────────────────────────────────────────────────────────


def create_feature_mcp_server(project_dir: Path) -> McpSdkServerConfig:
    """Create in-process feature MCP server for the given project directory.

    Zero cold-start cost vs AutoForge's ~400ms subprocess spawn per session.
    Tools run in-process with direct SQLAlchemy DB access.

    Args:
        project_dir: Root directory of the project. DB lives at
            <project_dir>/.claw-forge/features.db

    Returns:
        McpSdkServerConfig ready to be passed to ClaudeAgentOptions.mcp_servers
        under the ``"features"`` key.

    Example::

        from claw_forge.mcp.sdk_server import create_feature_mcp_server
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(
            mcp_servers={"features": create_feature_mcp_server(Path("/my/project"))},
        )
    """
    tools = _make_tools(project_dir)
    return create_sdk_mcp_server("features", tools=tools)
