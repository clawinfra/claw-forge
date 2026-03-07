"""Tests for session manifest."""

import tempfile

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

    def test_hydrate_prompt_no_description_skips_block(self):
        """Empty description branch (89->91) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="MyApp", description="")
        prompt = m.hydrate_prompt()
        assert "MyApp" in prompt
        # description block (just the value) should not appear
        assert prompt.count("\n\n") == 0 or "description" not in prompt.lower()

    def test_hydrate_prompt_no_language_skips_language_line(self):
        """Empty language branch (91->93) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="App", language="")
        prompt = m.hydrate_prompt()
        assert "Language:" not in prompt

    def test_hydrate_prompt_no_framework_skips_framework_line(self):
        """Empty framework branch (93->96) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="App", framework="")
        prompt = m.hydrate_prompt()
        assert "Framework:" not in prompt

    def test_hydrate_prompt_no_files_skips_files_section(self):
        """No files branch (96->104) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="App", files=[])
        prompt = m.hydrate_prompt()
        assert "## Key Files" not in prompt

    def test_hydrate_prompt_file_without_summary(self):
        """File with no summary (100->102) skips summary annotation."""
        m = SessionManifest(
            project_path="/tmp/test",
            project_name="App",
            files=[FileContext(path="main.py", role="context")],  # no summary
        )
        prompt = m.hydrate_prompt()
        assert "main.py" in prompt
        # No summary annotation after the file path
        file_line = [ln for ln in prompt.splitlines() if "main.py" in ln][0]
        assert ":" not in file_line.split("main.py")[1]

    def test_hydrate_prompt_no_skills_skips_skills_section(self):
        """No skills branch (104->109) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="App", skills=[])
        prompt = m.hydrate_prompt()
        assert "## Active Skills" not in prompt

    def test_hydrate_prompt_no_decisions_skips_decisions_section(self):
        """No decisions branch (109->114) not included."""
        m = SessionManifest(project_path="/tmp/test", project_name="App", decisions=[])
        prompt = m.hydrate_prompt()
        assert "## Prior Decisions" not in prompt

    def test_hydrate_prompt_uses_project_path_when_no_name(self):
        """When project_name is empty, project_path is used in header."""
        m = SessionManifest(project_path="/my/project", project_name="")
        prompt = m.hydrate_prompt()
        assert "/my/project" in prompt
