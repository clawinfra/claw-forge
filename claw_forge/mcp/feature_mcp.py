"""Feature MCP server — exposes feature management tools to Claude agents.

This MCP server bridges the gap between claw-forge's REST API and the
Claude agent SDK. Agents use MCP tools to claim, update, and query features
instead of calling the REST API directly.

Usage:
    # Start as a subprocess (auto-managed by mcp_server_config)
    python -m claw_forge.mcp.feature_mcp

    # Get the config dict for ClaudeAgentOptions.mcp_servers
    from claw_forge.mcp.feature_mcp import mcp_server_config
    config = mcp_server_config(Path("/my/project"))
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

from mcp.server.fastmcp import FastMCP
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.orm import Session as DBSession

# ── DB Models ────────────────────────────────────────────────────────────────


class FeatureBase(DeclarativeBase):
    pass


class Feature(FeatureBase):
    """A single implementable feature tracked by claw-forge."""
    __tablename__ = "features"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category = Column(String(128), nullable=False, default="general")
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    steps = Column(JSON, default=list)  # list of step strings
    status: Column[Any] = Column(
        Enum(
            "pending",
            "in_progress",
            "passing",
            "failing",
            "skipped",
            name="feature_status",
        ),
        default="pending",
        nullable=False,
    )
    claimed_by = Column(String(128), nullable=True)  # agent session ID
    fail_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    dependencies = relationship(
        "FeatureDependency",
        foreign_keys="FeatureDependency.feature_id",
        back_populates="feature",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "steps": self.steps or [],
            "status": self.status,
            "claimed_by": self.claimed_by,
            "fail_reason": self.fail_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "depends_on": [d.depends_on_id for d in self.dependencies],
        }


class FeatureDependency(FeatureBase):
    """A directed dependency edge between features."""
    __tablename__ = "feature_dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_id = Column(String(36), ForeignKey("features.id"), nullable=False)
    depends_on_id = Column(String(36), ForeignKey("features.id"), nullable=False)

    feature = relationship(
        "Feature",
        foreign_keys="[FeatureDependency.feature_id]",
        back_populates="dependencies",
    )


# ── DB helpers ───────────────────────────────────────────────────────────────


def _get_db_path() -> Path:
    """Resolve the features database path from PROJECT_DIR env var."""
    project_dir = os.environ.get("PROJECT_DIR", ".")
    return Path(project_dir) / ".claw-forge" / "features.db"


def _get_engine() -> Engine:
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    FeatureBase.metadata.create_all(engine)
    return engine


def _deps_satisfied(session: DBSession, feature: Feature) -> bool:
    """Return True if all dependencies for this feature are passing."""
    for dep in feature.dependencies:
        dep_feature = session.get(Feature, dep.depends_on_id)
        if dep_feature is None or dep_feature.status != "passing":
            return False
    return True


# ── MCP server ───────────────────────────────────────────────────────────────

mcp = FastMCP("claw-forge-features")


@mcp.tool()
def feature_get_stats() -> dict[str, int]:
    """Get feature counts by status."""
    engine = _get_engine()
    with DBSession(engine) as session:
        all_features = session.execute(select(Feature)).scalars().all()
        stats: dict[str, int] = {
            "total": len(all_features),
            "pending": 0,
            "in_progress": 0,
            "passing": 0,
            "failing": 0,
            "skipped": 0,
        }
        for f in all_features:
            status = str(f.status or "pending")
            if status in stats:
                stats[status] += 1
        return stats


@mcp.tool()
def feature_get_by_id(feature_id: str) -> dict[str, Any] | None:
    """Get a feature by its ID. Returns None if not found."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        return feature.to_dict()


@mcp.tool()
def feature_get_summary() -> list[dict[str, Any]]:
    """Get a summary list of all features (id, name, status, category)."""
    engine = _get_engine()
    with DBSession(engine) as session:
        features = session.execute(select(Feature)).scalars().all()
        return [
            {
                "id": f.id,
                "category": f.category,
                "name": f.name,
                "status": f.status,
                "claimed_by": f.claimed_by,
            }
            for f in features
        ]


@mcp.tool()
def feature_get_ready() -> list[dict[str, Any]]:
    """Get features that are pending and have all dependencies satisfied."""
    engine = _get_engine()
    with DBSession(engine) as session:
        pending = (
            session.execute(
                select(Feature).where(Feature.status == "pending")
            )
            .scalars()
            .all()
        )
        return [f.to_dict() for f in pending if _deps_satisfied(session, f)]


@mcp.tool()
def feature_get_blocked() -> list[dict[str, Any]]:
    """Get pending features that have unmet dependencies."""
    engine = _get_engine()
    with DBSession(engine) as session:
        pending = (
            session.execute(
                select(Feature).where(Feature.status == "pending")
            )
            .scalars()
            .all()
        )
        return [f.to_dict() for f in pending if not _deps_satisfied(session, f)]


@mcp.tool()
def feature_get_graph() -> list[dict[str, Any]]:
    """Get the full feature dependency graph."""
    engine = _get_engine()
    with DBSession(engine) as session:
        features = session.execute(select(Feature)).scalars().all()
        return [f.to_dict() for f in features]


@mcp.tool()
def feature_claim_and_get(agent_id: str = "") -> dict[str, Any] | None:
    """Atomically claim the next available (ready) feature for an agent.

    Returns the claimed feature or None if nothing is available.
    agent_id is used to tag the claimed_by field.
    """
    engine = _get_engine()
    with DBSession(engine) as session:
        pending = (
            session.execute(
                select(Feature).where(Feature.status == "pending")
            )
            .scalars()
            .all()
        )
        for feature in pending:
            if _deps_satisfied(session, feature):
                feature.status = "in_progress"  # type: ignore[assignment]
                feature.claimed_by = agent_id or "unknown"  # type: ignore[assignment]
                feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
                session.commit()
                session.refresh(feature)
                return feature.to_dict()
        return None


@mcp.tool()
def feature_mark_in_progress(feature_id: str) -> dict[str, Any] | None:
    """Mark a feature as in_progress."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        feature.status = "in_progress"  # type: ignore[assignment]
        feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_mark_passing(feature_id: str) -> dict[str, Any] | None:
    """Mark a feature as passing (completed successfully)."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        feature.status = "passing"  # type: ignore[assignment]
        feature.claimed_by = None  # type: ignore[assignment]
        feature.fail_reason = None  # type: ignore[assignment]
        feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_mark_failing(feature_id: str, reason: str = "") -> dict[str, Any] | None:
    """Mark a feature as failing with an optional reason."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        feature.status = "failing"  # type: ignore[assignment]
        feature.fail_reason = reason  # type: ignore[assignment]
        feature.claimed_by = None  # type: ignore[assignment]
        feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_clear_in_progress(feature_id: str) -> dict[str, Any] | None:
    """Release a claim on a feature — resets it back to pending."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        feature.status = "pending"  # type: ignore[assignment]
        feature.claimed_by = None  # type: ignore[assignment]
        feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_skip(feature_id: str) -> dict[str, Any] | None:
    """Mark a feature as skipped."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return None
        feature.status = "skipped"  # type: ignore[assignment]
        feature.claimed_by = None  # type: ignore[assignment]
        feature.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_create(
    name: str,
    category: str = "general",
    description: str = "",
    steps: list[str] | None = None,
) -> dict[str, Any]:
    """Create a single feature."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = Feature(
            id=str(uuid.uuid4()),
            name=name,
            category=category,
            description=description,
            steps=steps or [],
            status="pending",
        )
        session.add(feature)
        session.commit()
        session.refresh(feature)
        return feature.to_dict()


@mcp.tool()
def feature_create_bulk(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch create features.

    Each item in the list should have: name, category (optional),
    description (optional), steps (optional).
    """
    engine = _get_engine()
    created = []
    with DBSession(engine) as session:
        for item in features:
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
    return created


@mcp.tool()
def feature_add_dependency(feature_id: str, depends_on_id: str) -> bool:
    """Add a dependency: feature_id depends on depends_on_id."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        depends_on = session.get(Feature, depends_on_id)
        if feature is None or depends_on is None:
            return False
        # Check for duplicate
        existing = [d for d in feature.dependencies if d.depends_on_id == depends_on_id]
        if existing:
            return True  # already exists
        dep = FeatureDependency(feature_id=feature_id, depends_on_id=depends_on_id)
        session.add(dep)
        session.commit()
        return True


@mcp.tool()
def feature_set_dependencies(feature_id: str, depends_on_ids: list[str]) -> bool:
    """Replace all dependencies for a feature with the given list."""
    engine = _get_engine()
    with DBSession(engine) as session:
        feature = session.get(Feature, feature_id)
        if feature is None:
            return False
        # Remove all existing deps
        for dep in list(feature.dependencies):
            session.delete(dep)
        session.flush()
        # Add new deps
        for dep_id in depends_on_ids:
            dep = FeatureDependency(feature_id=feature_id, depends_on_id=dep_id)
            session.add(dep)
        session.commit()
        return True


# ── Config helper ─────────────────────────────────────────────────────────────


def mcp_server_config(project_dir: Path) -> dict[str, Any]:
    """Return the MCP server config dict for ClaudeAgentOptions.mcp_servers."""
    return {
        "features": {
            "command": sys.executable,
            "args": ["-m", "claw_forge.mcp.feature_mcp"],
            "env": {"PROJECT_DIR": str(project_dir.resolve())},
        }
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
