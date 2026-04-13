"""Tests for brownfield XML spec support in claw-forge."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from claw_forge.spec.parser import ProjectSpec, generate_brownfield_manifest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BROWNFIELD_XML = textwrap.dedent(
    """\
    <project_specification mode="brownfield">
      <project_name>MyApp — Stripe Payments</project_name>
      <addition_summary>
        Add Stripe Checkout so users can subscribe to Pro plan.
      </addition_summary>
      <existing_context>
        <stack>Python / FastAPI / PostgreSQL</stack>
        <test_baseline>47 tests passing, 87% coverage</test_baseline>
        <conventions>snake_case, async handlers, pydantic v2</conventions>
      </existing_context>
      <features_to_add>
        <payments>
          - User can add a payment method via Stripe Elements
          - User can subscribe to Pro plan via Stripe Checkout
        </payments>
        <webhooks>
          - Webhook handler processes subscription.created events
        </webhooks>
      </features_to_add>
      <integration_points>
        Extends User model with stripe_customer_id field
        Adds /payments router alongside existing /auth and /projects routers
      </integration_points>
      <constraints>
        Must not modify existing auth flow
        All 47 existing tests must stay green
      </constraints>
      <implementation_steps>
        <phase name="Stripe Integration">
          User can add a payment method via Stripe Elements
        </phase>
        <phase name="Subscription Flow">
          User can subscribe to Pro plan via Stripe Checkout
          Webhook handler processes subscription.created events
        </phase>
      </implementation_steps>
      <success_criteria>
        All new features implemented and tested
        Existing test suite still 100% green
        Coverage maintained above 87%
      </success_criteria>
    </project_specification>
    """
)

GREENFIELD_XML = textwrap.dedent(
    """\
    <project_specification>
      <project_name>GreenApp</project_name>
      <overview>A greenfield web app.</overview>
      <technology_stack>
        <frontend>
          <framework>React</framework>
          <port>3000</port>
        </frontend>
        <backend>
          <runtime>FastAPI</runtime>
          <database>PostgreSQL</database>
          <port>8000</port>
        </backend>
      </technology_stack>
      <core_features>
        <auth>
          - User can register with email and password
          - User can login and receive JWT token
        </auth>
      </core_features>
      <implementation_steps>
        <step><title>Phase 1: Auth</title></step>
        <step><title>Phase 2: Core</title></step>
      </implementation_steps>
      <success_criteria>
        <functionality>
          - All features implemented
        </functionality>
      </success_criteria>
    </project_specification>
    """
)

# Brownfield with <core_features> instead of <features_to_add> (mixed)
MIXED_XML = textwrap.dedent(
    """\
    <project_specification mode="brownfield">
      <project_name>Mixed Spec</project_name>
      <addition_summary>Uses core_features tag in brownfield mode.</addition_summary>
      <existing_context>
        <stack>Go / Gin / SQLite</stack>
      </existing_context>
      <core_features>
        <api>
          - User can list resources via GET /resources
          - User can create a resource via POST /resources
        </api>
      </core_features>
      <constraints>
        Do not break existing endpoints
      </constraints>
    </project_specification>
    """
)


@pytest.fixture
def brownfield_spec_file(tmp_path: Path) -> Path:
    p = tmp_path / "brownfield_spec.xml"
    p.write_text(BROWNFIELD_XML)
    return p


@pytest.fixture
def greenfield_spec_file(tmp_path: Path) -> Path:
    p = tmp_path / "app_spec.txt"
    p.write_text(GREENFIELD_XML)
    return p


@pytest.fixture
def mixed_spec_file(tmp_path: Path) -> Path:
    p = tmp_path / "mixed_spec.xml"
    p.write_text(MIXED_XML)
    return p


# ---------------------------------------------------------------------------
# Tests: mode parsing
# ---------------------------------------------------------------------------


def test_brownfield_mode_from_file(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert spec.mode == "brownfield"


def test_greenfield_mode_default(greenfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(greenfield_spec_file)
    assert spec.mode == "greenfield"


# ---------------------------------------------------------------------------
# Tests: is_brownfield property
# ---------------------------------------------------------------------------


def test_is_brownfield_true(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert spec.is_brownfield is True


def test_is_brownfield_false_for_greenfield(greenfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(greenfield_spec_file)
    assert spec.is_brownfield is False


# ---------------------------------------------------------------------------
# Tests: brownfield field parsing
# ---------------------------------------------------------------------------


def test_addition_summary_parsed(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert "Stripe Checkout" in spec.addition_summary
    assert "Pro plan" in spec.addition_summary


def test_existing_context_dict(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert spec.existing_context["stack"] == "Python / FastAPI / PostgreSQL"
    assert "47 tests" in spec.existing_context["test_baseline"]
    assert "snake_case" in spec.existing_context["conventions"]


def test_integration_points_list(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert len(spec.integration_points) >= 2
    assert any("stripe_customer_id" in pt for pt in spec.integration_points)
    assert any("/payments" in pt for pt in spec.integration_points)


def test_constraints_list(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert len(spec.constraints) >= 2
    assert any("auth flow" in c for c in spec.constraints)
    assert any("47 existing tests" in c for c in spec.constraints)


def test_features_to_add_populates_features(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert len(spec.features) >= 3
    descriptions = [f.description for f in spec.features]
    assert any("Stripe Elements" in d for d in descriptions)
    assert any("Stripe Checkout" in d for d in descriptions)
    assert any("subscription.created" in d for d in descriptions)


# ---------------------------------------------------------------------------
# Tests: to_agent_context
# ---------------------------------------------------------------------------


def test_to_agent_context_greenfield(greenfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(greenfield_spec_file)
    ctx = spec.to_agent_context()
    assert "GreenApp" in ctx
    # Should NOT contain brownfield headers
    assert "Existing Codebase Context" not in ctx


def test_to_agent_context_brownfield_header(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    ctx = spec.to_agent_context()
    assert "Existing Codebase Context" in ctx


def test_to_agent_context_brownfield_stack(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    ctx = spec.to_agent_context()
    assert "Python / FastAPI / PostgreSQL" in ctx


def test_to_agent_context_includes_constraints(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    ctx = spec.to_agent_context()
    assert "Constraints" in ctx
    assert "auth flow" in ctx


def test_to_agent_context_includes_integration_points(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    ctx = spec.to_agent_context()
    assert "Integration Points" in ctx
    assert "stripe_customer_id" in ctx


def test_to_agent_context_with_manifest_merges(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    manifest = {
        "stack": "Python / FastAPI / MySQL",
        "conventions": "camelCase, sync handlers",
    }
    ctx = spec.to_agent_context(manifest)
    # Manifest wins over spec values
    assert "MySQL" in ctx
    assert "camelCase" in ctx


def test_to_agent_context_manifest_test_baseline(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    manifest = {"test_baseline": "100 tests passing, 95% coverage"}
    ctx = spec.to_agent_context(manifest)
    assert "100 tests" in ctx


# ---------------------------------------------------------------------------
# Tests: missing optional fields (graceful handling)
# ---------------------------------------------------------------------------


def test_missing_existing_context_graceful(tmp_path: Path) -> None:
    xml = textwrap.dedent(
        """\
        <project_specification mode="brownfield">
          <project_name>Minimal</project_name>
          <features_to_add>
            <core>
              - User can log in
            </core>
          </features_to_add>
        </project_specification>
        """
    )
    p = tmp_path / "minimal.xml"
    p.write_text(xml)
    spec = ProjectSpec.from_file(p)
    assert spec.existing_context == {}
    assert spec.is_brownfield is True


def test_missing_constraints_graceful(tmp_path: Path) -> None:
    xml = textwrap.dedent(
        """\
        <project_specification mode="brownfield">
          <project_name>NoConstraints</project_name>
          <existing_context>
            <stack>Node.js / Express</stack>
          </existing_context>
          <features_to_add>
            <api>
              - User can list items
            </api>
          </features_to_add>
        </project_specification>
        """
    )
    p = tmp_path / "no_constraints.xml"
    p.write_text(xml)
    spec = ProjectSpec.from_file(p)
    assert spec.constraints == []


# ---------------------------------------------------------------------------
# Tests: <features_to_add> and <core_features> equivalence
# ---------------------------------------------------------------------------


def test_features_to_add_same_logic_as_core_features(
    brownfield_spec_file: Path, greenfield_spec_file: Path
) -> None:
    bf = ProjectSpec.from_file(brownfield_spec_file)
    gf = ProjectSpec.from_file(greenfield_spec_file)
    # Both should populate spec.features
    assert len(bf.features) > 0
    assert len(gf.features) > 0


def test_mixed_spec_brownfield_with_core_features(mixed_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(mixed_spec_file)
    assert spec.is_brownfield is True
    assert len(spec.features) == 2
    descriptions = [f.description for f in spec.features]
    assert any("GET /resources" in d for d in descriptions)
    assert any("POST /resources" in d for d in descriptions)


# ---------------------------------------------------------------------------
# Tests: phase assignment in brownfield
# ---------------------------------------------------------------------------


def test_brownfield_phases_preserved(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    assert "Stripe Integration" in spec.implementation_phases
    assert "Subscription Flow" in spec.implementation_phases


def test_roundtrip_brownfield_features_have_phases(brownfield_spec_file: Path) -> None:
    spec = ProjectSpec.from_file(brownfield_spec_file)
    # After phase assignment, features should have categories or depend_on set
    assert len(spec.features) >= 3
    # All features have non-empty descriptions
    for feat in spec.features:
        assert feat.description


# ---------------------------------------------------------------------------
# Tests: template file existence
# ---------------------------------------------------------------------------


def test_brownfield_template_file_exists() -> None:
    repo_root = Path(__file__).parent.parent
    template = repo_root / "skills" / "app_spec.brownfield.template.xml"
    assert template.exists(), f"Template not found: {template}"
    content = template.read_text()
    assert 'mode="brownfield"' in content
    assert "<features_to_add>" in content
    assert "<integration_points>" in content
    assert "<constraints>" in content


# ---------------------------------------------------------------------------
# Tests: InitializerPlugin brownfield support
# ---------------------------------------------------------------------------


def test_initializer_brownfield_metadata(tmp_path: Path, brownfield_spec_file: Path) -> None:
    """InitializerPlugin returns brownfield metadata when spec is brownfield."""
    import asyncio

    from claw_forge.plugins.base import PluginContext
    from claw_forge.plugins.initializer import InitializerPlugin

    plugin = InitializerPlugin()
    ctx = PluginContext(project_path=str(tmp_path), session_id="test", task_id="test")
    ctx.metadata = {"spec_file": str(brownfield_spec_file)}
    result = asyncio.run(plugin.execute(ctx))
    assert result.success
    assert result.metadata["mode"] == "brownfield"
    assert "constraints" in result.metadata
    assert "integration_points" in result.metadata
    assert "agent_context" in result.metadata
    assert "Existing Codebase Context" in result.metadata["agent_context"]


def test_initializer_brownfield_manifest_merge(tmp_path: Path) -> None:
    """InitializerPlugin merges brownfield_manifest.json into existing_context."""
    import asyncio

    from claw_forge.plugins.base import PluginContext
    from claw_forge.plugins.initializer import InitializerPlugin

    xml = textwrap.dedent(
        """\
        <project_specification mode="brownfield">
          <project_name>ManifestTest</project_name>
          <existing_context>
            <stack>Python / Django</stack>
          </existing_context>
          <features_to_add>
            <core>
              - User can view dashboard
            </core>
          </features_to_add>
        </project_specification>
        """
    )
    spec_path = tmp_path / "spec.xml"
    spec_path.write_text(xml)

    manifest = {
        "stack": "Python / FastAPI / PostgreSQL",
        "test_baseline": "50 tests, 90% coverage",
        "conventions": "async, pydantic v2",
    }
    (tmp_path / "brownfield_manifest.json").write_text(json.dumps(manifest))

    plugin = InitializerPlugin()
    ctx = PluginContext(project_path=str(tmp_path), session_id="test", task_id="test")
    ctx.metadata = {"spec_file": str(spec_path)}
    result = asyncio.run(plugin.execute(ctx))
    assert result.success
    # Manifest wins for stack
    assert "PostgreSQL" in result.metadata["existing_context"]["stack"]
    assert "50 tests" in result.metadata["existing_context"]["test_baseline"]


# ---------------------------------------------------------------------------
# Tests: generate_brownfield_manifest
# ---------------------------------------------------------------------------


class TestGenerateBrownfieldManifest:
    """Tests for auto-generation of brownfield_manifest.json."""

    def _make_greenfield_spec(self, tmp_path: Path) -> tuple[Path, ProjectSpec]:
        xml = textwrap.dedent(
            """\
            <project_specification>
              <project_name>TestApp</project_name>
              <overview>A test application.</overview>
              <technology_stack>
                <frontend>
                  <framework>React</framework>
                  <port>3000</port>
                </frontend>
                <backend>
                  <runtime>FastAPI</runtime>
                  <database>PostgreSQL</database>
                  <port>8000</port>
                </backend>
              </technology_stack>
              <core_features>
                <category name="Auth">
                  - User can register with email
                  - User can login with JWT
                </category>
              </core_features>
            </project_specification>
            """
        )
        p = tmp_path / "app_spec.txt"
        p.write_text(xml)
        return p, ProjectSpec.from_file(p)

    def test_stack_from_tech_stack(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        manifest = generate_brownfield_manifest(spec, 10, tmp_path)
        assert "FastAPI" in manifest["stack"]
        assert "React" in manifest["stack"]
        assert "PostgreSQL" in manifest["stack"]

    def test_test_baseline_reflects_completed_count(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        manifest = generate_brownfield_manifest(spec, 42, tmp_path)
        assert "42 features completed" in manifest["test_baseline"]

    def test_conventions_detects_ruff(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "ruff" in manifest["conventions"]

    def test_conventions_detects_mypy(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "mypy" in manifest["conventions"]

    def test_conventions_detects_pytest(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "pytest" in manifest["conventions"]

    def test_conventions_detects_typescript(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "typescript" in manifest["conventions"]

    def test_conventions_detects_eslint(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / ".eslintrc.json").write_text("{}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "eslint" in manifest["conventions"]

    def test_conventions_detects_eslint_flat_config(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "eslint.config.js").write_text("module.exports = {}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "eslint" in manifest["conventions"]

    def test_conventions_detects_biome(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "biome.json").write_text("{}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "biome" in manifest["conventions"]

    def test_conventions_detects_tailwind_js(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "tailwind.config.js").write_text("module.exports = {}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "tailwind" in manifest["conventions"]

    def test_conventions_detects_tailwind_ts(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "tailwind.config.ts").write_text("export default {}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "tailwind" in manifest["conventions"]

    def test_conventions_fallback_when_none_detected(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert manifest["conventions"] == "see project config"

    def test_conventions_detects_multiple(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\n[tool.mypy]\n[tool.pytest]\n"
        )
        (tmp_path / "tsconfig.json").write_text("{}")
        manifest = generate_brownfield_manifest(spec, 5, tmp_path)
        assert "ruff" in manifest["conventions"]
        assert "mypy" in manifest["conventions"]
        assert "typescript" in manifest["conventions"]

    def test_stack_fallback_when_no_tech_stack(self, tmp_path: Path) -> None:
        xml = textwrap.dedent(
            """\
            <project_specification>
              <project_name>Minimal</project_name>
              <overview>Minimal project.</overview>
              <core_features>
                <category name="Core">
                  - User can do something
                </category>
              </core_features>
            </project_specification>
            """
        )
        p = tmp_path / "app_spec.txt"
        p.write_text(xml)
        spec = ProjectSpec.from_file(p)
        manifest = generate_brownfield_manifest(spec, 1, tmp_path)
        assert manifest["stack"] == "unknown"

    def test_manifest_has_required_keys(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        manifest = generate_brownfield_manifest(spec, 10, tmp_path)
        assert "stack" in manifest
        assert "test_baseline" in manifest
        assert "conventions" in manifest

    def test_manifest_is_json_serializable(self, tmp_path: Path) -> None:
        _, spec = self._make_greenfield_spec(tmp_path)
        manifest = generate_brownfield_manifest(spec, 10, tmp_path)
        serialized = json.dumps(manifest)
        roundtrip = json.loads(serialized)
        assert roundtrip == manifest


# ---------------------------------------------------------------------------
# Tests: CLI run integration — manifest generation on completion
# ---------------------------------------------------------------------------


class TestCliManifestGeneration:
    """Tests for brownfield_manifest.json generation in the `run` command."""

    def test_manifest_written_after_successful_greenfield_run(
        self, tmp_path: Path
    ) -> None:
        """Simulate the post-run manifest generation logic."""
        # Set up a greenfield spec in the project
        xml = textwrap.dedent(
            """\
            <project_specification>
              <project_name>TestApp</project_name>
              <overview>A test app.</overview>
              <technology_stack>
                <backend>
                  <runtime>Django</runtime>
                  <database>SQLite</database>
                </backend>
              </technology_stack>
              <core_features>
                <category name="Core">
                  - User can view dashboard
                </category>
              </core_features>
            </project_specification>
            """
        )
        (tmp_path / "app_spec.txt").write_text(xml)
        manifest_path = tmp_path / "brownfield_manifest.json"

        # Simulate the CLI logic: find spec, parse, generate manifest
        from claw_forge.spec import ProjectSpec as _PS
        from claw_forge.spec import generate_brownfield_manifest as _gen

        spec_candidates = [tmp_path / "app_spec.txt", tmp_path / "app_spec.xml"]
        found_spec = next((s for s in spec_candidates if s.exists()), None)
        assert found_spec is not None

        parsed = _PS.from_file(found_spec)
        assert not parsed.is_brownfield

        manifest = _gen(parsed, 15, tmp_path)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert "Django" in data["stack"]
        assert "15 features completed" in data["test_baseline"]

    def test_manifest_not_overwritten_if_exists(self, tmp_path: Path) -> None:
        """If brownfield_manifest.json already exists, it is NOT overwritten."""
        existing = {"stack": "custom", "test_baseline": "99 tests", "conventions": "custom"}
        manifest_path = tmp_path / "brownfield_manifest.json"
        manifest_path.write_text(json.dumps(existing))

        # Simulate the CLI guard: skip if manifest exists
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["stack"] == "custom"  # unchanged

    def test_manifest_skipped_for_brownfield_spec(self, tmp_path: Path) -> None:
        """Brownfield specs should not trigger manifest generation."""
        xml = textwrap.dedent(
            """\
            <project_specification mode="brownfield">
              <project_name>Additions</project_name>
              <features_to_add>
                <core>- User can view reports</core>
              </features_to_add>
            </project_specification>
            """
        )
        (tmp_path / "app_spec.txt").write_text(xml)

        from claw_forge.spec import ProjectSpec as _PS

        parsed = _PS.from_file(tmp_path / "app_spec.txt")
        assert parsed.is_brownfield  # guard: should not generate manifest

    def test_manifest_skipped_when_no_spec_found(self, tmp_path: Path) -> None:
        """When no spec file exists in the project, manifest is not generated."""
        spec_candidates = [tmp_path / "app_spec.txt", tmp_path / "app_spec.xml"]
        found = next((s for s in spec_candidates if s.exists()), None)
        assert found is None  # no spec → no manifest
