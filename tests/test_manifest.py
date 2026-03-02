"""Tests for session manifest."""

import json
import tempfile
from pathlib import Path

from claw_forge.state.manifest import FileContext, SessionManifest, SkillRef


class TestSessionManifest:
    def test_roundtrip_json(self):
        m = SessionManifest(
            project_path="/tmp/test",
            project_name="test",
            language="python",
            files=[FileContext(path="main.py", role="context")],
            skills=[SkillRef(name="pyright")],
            decisions=["Use asyncio"],
        )
        j = m.to_json()
        m2 = SessionManifest.from_json(j)
        assert m2.project_name == "test"
        assert len(m2.files) == 1
        assert len(m2.skills) == 1

    def test_hydrate_prompt(self):
        m = SessionManifest(
            project_path="/tmp/test",
            project_name="MyProject",
            language="python",
            framework="fastapi",
            description="A cool project",
            files=[FileContext(path="app.py", role="context", summary="Main app")],
            skills=[SkillRef(name="pyright")],
            decisions=["Use async everywhere"],
        )
        prompt = m.hydrate_prompt()
        assert "MyProject" in prompt
        assert "python" in prompt
        assert "app.py" in prompt
        assert "pyright" in prompt
        assert "Use async everywhere" in prompt

    def test_save_and_load(self):
        m = SessionManifest(project_path="/tmp/test", project_name="test")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            m.save(f.name)
            loaded = SessionManifest.from_file(f.name)
            assert loaded.project_name == "test"
