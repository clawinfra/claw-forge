"""Tests for claw_forge.mcp.feature_mcp — mock-based tests for MCP tool functions."""
from __future__ import annotations

import sys
import uuid

import pytest

# We test the underlying functions directly (not through MCP protocol)
# by patching _get_engine to use an in-memory SQLite database.
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession


def _make_in_memory_engine():
    """Create a fresh in-memory SQLite engine with the feature schema."""
    from claw_forge.mcp.feature_mcp import FeatureBase
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    FeatureBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Fixture that patches _get_engine to use an in-memory DB."""
    _engine = _make_in_memory_engine()
    monkeypatch.setattr("claw_forge.mcp.feature_mcp._get_engine", lambda: _engine)
    return _engine


@pytest.fixture
def sample_features(engine):
    """Create a few sample features for testing."""
    from claw_forge.mcp.feature_mcp import Feature
    features = []
    with DBSession(engine) as session:
        for i in range(3):
            f = Feature(
                id=str(uuid.uuid4()),
                name=f"Feature {i}",
                category="test",
                description=f"Description {i}",
                steps=[f"Step {i}.1", f"Step {i}.2"],
                status="pending",
            )
            session.add(f)
            features.append(f)
        session.commit()
        for f in features:
            session.refresh(f)
        feature_dicts = [f.to_dict() for f in features]
    return feature_dicts


class TestFeatureGetStats:
    def test_empty_db_returns_zeros(self, engine):
        from claw_forge.mcp.feature_mcp import feature_get_stats
        stats = feature_get_stats()
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["passing"] == 0

    def test_counts_pending_features(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_get_stats
        stats = feature_get_stats()
        assert stats["total"] == 3
        assert stats["pending"] == 3

    def test_counts_after_status_change(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_get_stats, feature_mark_passing
        feature_mark_passing(sample_features[0]["id"])
        stats = feature_get_stats()
        assert stats["passing"] == 1
        assert stats["pending"] == 2


class TestFeatureGetById:
    def test_returns_feature(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_get_by_id
        result = feature_get_by_id(sample_features[0]["id"])
        assert result is not None
        assert result["name"] == "Feature 0"

    def test_returns_none_for_missing(self, engine):
        from claw_forge.mcp.feature_mcp import feature_get_by_id
        result = feature_get_by_id("nonexistent-id")
        assert result is None


class TestFeatureCreate:
    def test_creates_feature(self, engine):
        from claw_forge.mcp.feature_mcp import feature_create, feature_get_stats
        result = feature_create(name="New Feature", category="test", description="A feature")
        assert result["id"] is not None
        assert result["name"] == "New Feature"
        assert result["status"] == "pending"
        stats = feature_get_stats()
        assert stats["total"] == 1

    def test_create_with_steps(self, engine):
        from claw_forge.mcp.feature_mcp import feature_create
        result = feature_create(name="Feature", steps=["step1", "step2"])
        assert result["steps"] == ["step1", "step2"]


class TestFeatureCreateBulk:
    def test_creates_multiple(self, engine):
        from claw_forge.mcp.feature_mcp import feature_create_bulk, feature_get_stats
        items = [
            {"name": "F1", "category": "a"},
            {"name": "F2", "category": "b"},
            {"name": "F3", "category": "c"},
        ]
        results = feature_create_bulk(items)
        assert len(results) == 3
        stats = feature_get_stats()
        assert stats["total"] == 3


class TestFeatureMarkPassing:
    def test_marks_passing(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_mark_passing
        result = feature_mark_passing(sample_features[0]["id"])
        assert result["status"] == "passing"

    def test_returns_none_for_missing(self, engine):
        from claw_forge.mcp.feature_mcp import feature_mark_passing
        assert feature_mark_passing("nonexistent") is None


class TestFeatureMarkFailing:
    def test_marks_failing_with_reason(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_mark_failing
        result = feature_mark_failing(sample_features[0]["id"], reason="test failed")
        assert result["status"] == "failing"
        assert result["fail_reason"] == "test failed"

    def test_returns_none_for_missing(self, engine):
        from claw_forge.mcp.feature_mcp import feature_mark_failing
        assert feature_mark_failing("nonexistent", "reason") is None


class TestFeatureMarkInProgress:
    def test_marks_in_progress(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_mark_in_progress
        result = feature_mark_in_progress(sample_features[0]["id"])
        assert result["status"] == "in_progress"


class TestFeatureClearInProgress:
    def test_resets_to_pending(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_clear_in_progress, feature_mark_in_progress
        fid = sample_features[0]["id"]
        feature_mark_in_progress(fid)
        result = feature_clear_in_progress(fid)
        assert result["status"] == "pending"
        assert result["claimed_by"] is None


class TestFeatureClaimAndGet:
    def test_claims_pending_feature(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_claim_and_get
        result = feature_claim_and_get(agent_id="agent-1")
        assert result is not None
        assert result["status"] == "in_progress"
        assert result["claimed_by"] == "agent-1"

    def test_returns_none_when_nothing_available(self, engine):
        from claw_forge.mcp.feature_mcp import feature_claim_and_get
        result = feature_claim_and_get()
        assert result is None

    def test_respects_dependencies(self, engine):
        """A feature with unsatisfied deps should not be claimed."""
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_claim_and_get,
            feature_create,
        )
        dep = feature_create(name="Dependency")
        dependent = feature_create(name="Dependent")
        feature_add_dependency(dependent["id"], dep["id"])

        # Only "dep" has no deps, it should be claimed first
        claimed = feature_claim_and_get(agent_id="agent")
        assert claimed is not None
        assert claimed["id"] == dep["id"]


class TestFeatureGetReady:
    def test_pending_no_deps_is_ready(self, engine, sample_features):
        from claw_forge.mcp.feature_mcp import feature_get_ready
        ready = feature_get_ready()
        assert len(ready) == 3

    def test_feature_with_unmet_dep_not_ready(self, engine):
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_create,
            feature_get_ready,
        )
        dep = feature_create(name="Dep")
        dependent = feature_create(name="Dependent")
        feature_add_dependency(dependent["id"], dep["id"])
        ready = feature_get_ready()
        ready_ids = [f["id"] for f in ready]
        assert dep["id"] in ready_ids
        assert dependent["id"] not in ready_ids


class TestFeatureGetBlocked:
    def test_feature_with_unmet_dep_is_blocked(self, engine):
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_create,
            feature_get_blocked,
        )
        dep = feature_create(name="Dep")
        dependent = feature_create(name="Dependent")
        feature_add_dependency(dependent["id"], dep["id"])
        blocked = feature_get_blocked()
        blocked_ids = [f["id"] for f in blocked]
        assert dependent["id"] in blocked_ids
        assert dep["id"] not in blocked_ids


class TestFeatureAddDependency:
    def test_adds_dependency(self, engine):
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_create,
            feature_get_by_id,
        )
        a = feature_create(name="A")
        b = feature_create(name="B")
        result = feature_add_dependency(b["id"], a["id"])
        assert result is True
        b_detail = feature_get_by_id(b["id"])
        assert a["id"] in b_detail["depends_on"]

    def test_returns_false_for_missing_feature(self, engine):
        from claw_forge.mcp.feature_mcp import feature_add_dependency
        result = feature_add_dependency("nonexistent", "also-nonexistent")
        assert result is False


class TestFeatureSetDependencies:
    def test_replaces_dependencies(self, engine):
        from claw_forge.mcp.feature_mcp import (
            feature_add_dependency,
            feature_create,
            feature_get_by_id,
            feature_set_dependencies,
        )
        a = feature_create(name="A")
        b = feature_create(name="B")
        c = feature_create(name="C")
        feature_add_dependency(c["id"], a["id"])
        # Replace with b only
        result = feature_set_dependencies(c["id"], [b["id"]])
        assert result is True
        c_detail = feature_get_by_id(c["id"])
        assert b["id"] in c_detail["depends_on"]
        assert a["id"] not in c_detail["depends_on"]


class TestMcpServerConfig:
    def test_returns_features_key(self, tmp_path):
        from claw_forge.mcp.feature_mcp import mcp_server_config
        config = mcp_server_config(tmp_path)
        assert "features" in config

    def test_config_has_command(self, tmp_path):
        from claw_forge.mcp.feature_mcp import mcp_server_config
        config = mcp_server_config(tmp_path)
        assert "command" in config["features"]
        assert config["features"]["command"] == sys.executable

    def test_config_has_project_dir_env(self, tmp_path):
        from claw_forge.mcp.feature_mcp import mcp_server_config
        config = mcp_server_config(tmp_path)
        assert config["features"]["env"]["PROJECT_DIR"] == str(tmp_path.resolve())
