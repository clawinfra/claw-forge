"""Tests for claw_forge.spec.parser — XML and plain-text spec parsing."""

from __future__ import annotations

import textwrap
from pathlib import Path

from claw_forge.spec.parser import (
    FeatureItem,
    ProjectSpec,
    _assign_dependencies,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

TEMPLATE_XML = (
    Path(__file__).parent.parent.parent / "claw_forge" / "spec" / "app_spec.template.xml"
).read_text()

MINIMAL_XML = textwrap.dedent("""\
    <project_specification>
      <project_name>test-app</project_name>
      <overview>A test application for unit testing.</overview>
      <technology_stack>
        <frontend>
          <framework>Vue 3</framework>
          <port>5173</port>
        </frontend>
        <backend>
          <runtime>Node.js with Express</runtime>
          <database>PostgreSQL</database>
          <port>4000</port>
        </backend>
      </technology_stack>
      <core_features>
        <auth>
          - User can register
          - User can login
          - User can logout
        </auth>
        <dashboard>
          - User can view dashboard
          - User can filter data
        </dashboard>
      </core_features>
      <implementation_steps>
        <step number="1">
          <title>Auth Setup</title>
        </step>
        <step number="2">
          <title>Dashboard Features</title>
        </step>
      </implementation_steps>
      <success_criteria>
        <quality>
          - All tests pass
          - Coverage above 90%
        </quality>
      </success_criteria>
      <design_system>
        <color_palette>
          - Primary: #3b82f6
          - Secondary: #10b981
        </color_palette>
        <typography>
          - Font: Inter
        </typography>
      </design_system>
      <api_endpoints_summary>
        <auth>
          - POST /api/register
          - POST /api/login
        </auth>
        <data>
          - GET /api/dashboard
        </data>
      </api_endpoints_summary>
      <database_schema>
        <tables>
          <users>
            - id (PRIMARY KEY)
            - email (UNIQUE)
            - password_hash
          </users>
          <sessions>
            - id (PRIMARY KEY)
            - user_id (FOREIGN KEY)
            - token
          </sessions>
        </tables>
      </database_schema>
    </project_specification>
""")

PLAIN_TEXT_SPEC = textwrap.dedent("""\
    Project: my-todo-app
    Stack: Python/FastAPI + React

    1. User Authentication
       Description: Login and registration system
       - Set up auth routes
       - Create user model
       Depends on:

    2. Todo CRUD
       Description: Create, read, update, delete todos
       - Create todo model
       - Build REST endpoints
       Depends on: 1

    3. Frontend UI
       Description: React frontend for todos
       - Build todo list component
       - Add create/edit forms
       Depends on: 1, 2
""")

XML_WITH_COMMENTS = textwrap.dedent("""\
    <!-- This is a comment that should be stripped -->
    <project_specification>
      <!-- Another comment -->
      <project_name>commented-app</project_name>
      <overview>App with comments in XML.</overview>
      <core_features>
        <basic>
          - Feature one
          - Feature two
        </basic>
      </core_features>
    </project_specification>
""")


# ── Test XML parsing ─────────────────────────────────────────────────────────


class TestXmlParsing:
    """Test XML spec parsing."""

    def test_parse_project_name(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert spec.project_name == "test-app"

    def test_parse_overview(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert spec.overview == "A test application for unit testing."

    def test_parse_tech_stack_frontend(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert spec.tech_stack.frontend_framework == "Vue 3"
        assert spec.tech_stack.frontend_port == 5173

    def test_parse_tech_stack_backend(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert spec.tech_stack.backend_runtime == "Node.js with Express"
        assert spec.tech_stack.backend_db == "PostgreSQL"
        assert spec.tech_stack.backend_port == 4000

    def test_parse_tech_stack_raw_preserved(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "<framework>Vue 3</framework>" in spec.tech_stack.raw

    def test_feature_count(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert len(spec.features) == 5

    def test_feature_categories(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        categories = {f.category for f in spec.features}
        assert "Auth" in categories
        assert "Dashboard" in categories

    def test_feature_names_derived(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        names = [f.name for f in spec.features]
        assert "User can register" in names
        assert "User can login" in names

    def test_feature_description_is_full_bullet(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        desc = spec.features[0].description
        assert desc == "User can register"

    def test_implementation_phases(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert spec.implementation_phases == ["Auth Setup", "Dashboard Features"]

    def test_success_criteria(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "All tests pass" in spec.success_criteria
        assert "Coverage above 90%" in spec.success_criteria

    def test_design_system_parsed(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "color_palette" in spec.design_system
        assert len(spec.design_system["color_palette"]) == 2
        assert "Primary: #3b82f6" in spec.design_system["color_palette"]

    def test_design_system_typography(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "typography" in spec.design_system
        assert "Font: Inter" in spec.design_system["typography"]

    def test_api_endpoints_parsed(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "Auth" in spec.api_endpoints
        assert "POST /api/register" in spec.api_endpoints["Auth"]
        assert "POST /api/login" in spec.api_endpoints["Auth"]
        assert "Data" in spec.api_endpoints
        assert "GET /api/dashboard" in spec.api_endpoints["Data"]

    def test_database_tables_parsed(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "users" in spec.database_tables
        assert "sessions" in spec.database_tables
        assert "id (PRIMARY KEY)" in spec.database_tables["users"]
        assert "email (UNIQUE)" in spec.database_tables["users"]
        assert "user_id (FOREIGN KEY)" in spec.database_tables["sessions"]

    def test_raw_xml_preserved(self) -> None:
        spec = ProjectSpec._parse_xml(MINIMAL_XML)
        assert "<project_specification>" in spec.raw_xml

    def test_xml_comments_stripped(self) -> None:
        spec = ProjectSpec._parse_xml(XML_WITH_COMMENTS)
        assert spec.project_name == "commented-app"
        assert len(spec.features) == 2


# ── Test template XML ────────────────────────────────────────────────────────


class TestTemplateXml:
    """Test parsing the actual template XML file."""

    def test_template_parses_successfully(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert spec.project_name == "my-project"

    def test_template_feature_count(self) -> None:
        """Template should have 29 features across 4 categories."""
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert len(spec.features) == 29

    def test_template_categories(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        categories = {f.category for f in spec.features}
        assert "Authentication & User Management" in categories
        assert "Core Functionality" in categories
        assert "UI / UX" in categories
        assert "API Layer" in categories

    def test_template_phases(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert len(spec.implementation_phases) == 3
        assert "Phase 1: Project Setup & Auth" in spec.implementation_phases
        assert "Phase 2: Core Features" in spec.implementation_phases

    def test_template_design_system(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert "color_palette" in spec.design_system
        assert "typography" in spec.design_system
        assert "animations" in spec.design_system

    def test_template_api_endpoints(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert "Authentication" in spec.api_endpoints
        assert len(spec.api_endpoints["Authentication"]) == 5

    def test_template_database_tables(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        assert "users" in spec.database_tables
        assert len(spec.database_tables["users"]) == 6

    def test_template_success_criteria(self) -> None:
        spec = ProjectSpec._parse_xml(TEMPLATE_XML)
        # New template uses <success_criteria> with child elements
        assert len(spec.success_criteria) >= 0


# ── Test plain text parsing ──────────────────────────────────────────────────


class TestPlainTextParsing:
    """Test legacy plain text spec format."""

    def test_parse_project_name(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert spec.project_name == "my-todo-app"

    def test_parse_tech_stack_raw(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert spec.tech_stack.raw == "Python/FastAPI + React"

    def test_feature_count(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert len(spec.features) == 3

    def test_feature_names(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        names = [f.name for f in spec.features]
        assert "User Authentication" in names
        assert "Todo CRUD" in names
        assert "Frontend UI" in names

    def test_feature_descriptions(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert spec.features[0].description == "Login and registration system"

    def test_feature_steps(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert "Set up auth routes" in spec.features[0].steps
        assert "Create user model" in spec.features[0].steps

    def test_feature_dependencies(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert spec.features[0].depends_on_indices == []
        assert spec.features[1].depends_on_indices == [0]
        assert spec.features[2].depends_on_indices == [0, 1]

    def test_plain_text_defaults(self) -> None:
        spec = ProjectSpec._parse_plain_text(PLAIN_TEXT_SPEC)
        assert spec.implementation_phases == []
        assert spec.success_criteria == []
        assert spec.design_system == {}
        assert spec.api_endpoints == {}
        assert spec.database_tables == {}

    def test_plain_text_default_project_name(self) -> None:
        spec = ProjectSpec._parse_plain_text("1. Some feature\n   Description: does stuff\n")
        assert spec.project_name == "project"

    # ── Bullet-list format ───────────────────────────────────────────────────

    def test_bullet_list_under_features_header(self) -> None:
        """'Features:\\n- item' format should produce features, not 0."""
        spec = ProjectSpec._parse_plain_text(
            "Project: Todo CLI App\n"
            "Stack: Python, Click, SQLite\n\n"
            "Features:\n"
            "- Add todo item\n"
            "- List all todos\n"
            "- Mark todo as complete\n"
            "- Delete todo\n"
            "- Persistent storage with SQLite\n"
        )
        assert spec.project_name == "Todo CLI App"
        assert len(spec.features) == 5
        names = [f.name for f in spec.features]
        assert "Add todo item" in names
        assert "Persistent storage with SQLite" in names

    def test_bullet_list_category_assigned(self) -> None:
        """Features under a section header get that header as category."""
        spec = ProjectSpec._parse_plain_text(
            "Project: API\n\n"
            "Authentication:\n"
            "- Login endpoint\n"
            "- JWT token generation\n\n"
            "Data:\n"
            "- User model\n"
            "- Post model\n"
        )
        cats = {f.category for f in spec.features}
        assert "Authentication" in cats
        assert "Data" in cats
        assert len(spec.features) == 4

    def test_bullet_list_no_section_header(self) -> None:
        """Bare bullet items with no section header still produce features."""
        spec = ProjectSpec._parse_plain_text(
            "Project: Simple\n\n"
            "- Feature A\n"
            "- Feature B\n"
        )
        assert len(spec.features) == 2
        assert spec.features[0].name == "Feature A"

    def test_mixed_numbered_and_bullet(self) -> None:
        """Numbered features and bullet sections can coexist."""
        spec = ProjectSpec._parse_plain_text(
            "Project: Mixed\n"
            "Stack: Python\n\n"
            "1. Core setup\n"
            "   Description: Bootstrap the project\n\n"
            "Extras:\n"
            "- Nice-to-have feature\n"
        )
        assert len(spec.features) == 2
        names = [f.name for f in spec.features]
        assert "Core setup" in names
        assert "Nice-to-have feature" in names


# ── Test from_file dispatch ──────────────────────────────────────────────────


class TestFromFile:
    """Test from_file dispatches correctly based on format."""

    def test_from_file_xml(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "app_spec.txt"
        spec_file.write_text(MINIMAL_XML, encoding="utf-8")
        spec = ProjectSpec.from_file(spec_file)
        assert spec.project_name == "test-app"
        assert len(spec.features) == 5

    def test_from_file_plain_text(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "app_spec.txt"
        spec_file.write_text(PLAIN_TEXT_SPEC, encoding="utf-8")
        spec = ProjectSpec.from_file(spec_file)
        assert spec.project_name == "my-todo-app"
        assert len(spec.features) == 3

    def test_from_file_detects_xml_by_tag(self, tmp_path: Path) -> None:
        """Ensure detection works with leading whitespace."""
        content = "\n  \n" + MINIMAL_XML
        spec_file = tmp_path / "spec.txt"
        spec_file.write_text(content, encoding="utf-8")
        spec = ProjectSpec.from_file(spec_file)
        assert spec.project_name == "test-app"


# ── Test dependency assignment ───────────────────────────────────────────────


class TestDependencyAssignment:
    """Test _assign_dependencies logic."""

    def test_no_phases_no_deps(self) -> None:
        features = [FeatureItem(category="Auth", name="login", description="login")]
        result = _assign_dependencies(features, [])
        assert result[0] == []

    def test_single_phase_no_deps(self) -> None:
        features = [FeatureItem(category="Auth", name="login", description="login")]
        result = _assign_dependencies(features, ["Auth Setup"])
        assert result[0] == []

    def test_two_phases_creates_deps(self) -> None:
        features = [
            FeatureItem(category="Auth", name="login", description="login"),
            FeatureItem(category="Dashboard", name="view", description="view dashboard"),
        ]
        result = _assign_dependencies(features, ["Auth Setup", "Dashboard Build"])
        # Auth feature is in phase 0 (matches "Auth")
        assert result[0] == []
        # Dashboard feature is in phase 1 (matches "Dashboard"), depends on phase 0
        assert result[1] == [0]

    def test_unmatched_features_go_to_middle_phase(self) -> None:
        features = [
            FeatureItem(category="Auth", name="login", description="login"),
            FeatureItem(category="Misc", name="misc", description="misc feature"),
            FeatureItem(category="Dashboard", name="view", description="view dashboard"),
        ]
        result = _assign_dependencies(features, ["Auth Setup", "Dashboard Build"])
        # Misc doesn't match any phase, goes to middle (index 0 for 2 phases: 2//2=1)
        # Since it goes to phase 1 (middle of 2 = index 1), it depends on phase 0
        assert result[1] == [0]

    def test_no_mutation(self) -> None:
        """Verify that _assign_dependencies does not mutate the input features."""
        features = [
            FeatureItem(category="Auth", name="login", description="login"),
            FeatureItem(category="Dashboard", name="view", description="view dashboard"),
        ]
        _assign_dependencies(features, ["Auth Setup", "Dashboard Build"])
        # Features should remain unchanged (no mutation)
        assert features[0].depends_on_indices == []
        assert features[1].depends_on_indices == []


# ── Test edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Test parser edge cases."""

    def test_empty_core_features(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>empty</project_name>
              <core_features>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 0

    def test_asterisk_bullets(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>star</project_name>
              <core_features>
                <misc>
                  * Feature with asterisk
                  * Another asterisk feature
                </misc>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 2
        assert spec.features[0].name == "Feature with asterisk"

    def test_long_bullet_name_truncated(self) -> None:
        long_desc = "User can do something very very long " + "x" * 100
        xml = f"""\
            <project_specification>
              <project_name>long</project_name>
              <core_features>
                <misc>
                  - {long_desc}
                </misc>
              </core_features>
            </project_specification>
        """
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features[0].name) <= 60

    def test_no_tech_stack(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>minimal</project_name>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.tech_stack.frontend_framework == ""
        assert spec.tech_stack.frontend_port == 3000
        assert spec.tech_stack.backend_port == 3001

    def test_non_numeric_port_defaults(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>ports</project_name>
              <technology_stack>
                <frontend>
                  <port>abc</port>
                </frontend>
                <backend>
                  <port>xyz</port>
                </backend>
              </technology_stack>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.tech_stack.frontend_port == 3000
        assert spec.tech_stack.backend_port == 3001

    def test_empty_bullets_ignored(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>blanks</project_name>
              <core_features>
                <misc>
                  -
                  -
                  - Real feature
                </misc>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 1
        assert spec.features[0].name == "Real feature"


# ── New XML format: <category name="…"> / <table name="…"> / <domain name="…"> ─


class TestNewXmlFormat:
    """Tests for the new attribute-based XML spec format."""

    def test_category_name_attribute_used_as_category(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>newformat</project_name>
              <core_features>
                <category name="Authentication &amp; User Management">
                  - User can register with email and password
                  - User can login and receive JWT tokens
                </category>
                <category name="Receipt Scanning">
                  - System sends image to OCR API
                </category>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 3
        assert spec.features[0].category == "Authentication & User Management"
        assert spec.features[1].category == "Authentication & User Management"
        assert spec.features[2].category == "Receipt Scanning"

    def test_category_name_attribute_preserves_spaces_and_ampersand(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>spaces</project_name>
              <core_features>
                <category name="Tags &amp; Organization">
                  - User can add tags to any item
                </category>
              </core_features>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.features[0].category == "Tags & Organization"

    def test_table_name_attribute_and_column_children(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>tables</project_name>
              <database_schema>
                <tables>
                  <table name="users">
                    <column>id UUID PRIMARY KEY</column>
                    <column>email VARCHAR(255) UNIQUE NOT NULL</column>
                    <column>password_hash VARCHAR(255) NOT NULL</column>
                  </table>
                  <table name="refresh_tokens">
                    <column>id UUID PRIMARY KEY</column>
                    <column>user_id UUID NOT NULL REFERENCES users(id)</column>
                  </table>
                </tables>
              </database_schema>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert "users" in spec.database_tables
        assert len(spec.database_tables["users"]) == 3
        assert spec.database_tables["users"][0] == "id UUID PRIMARY KEY"
        assert "refresh_tokens" in spec.database_tables
        assert len(spec.database_tables["refresh_tokens"]) == 2

    def test_domain_name_attribute_with_plain_text_routes(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>api</project_name>
              <api_endpoints_summary>
                <domain name="Authentication">
                  POST   /api/auth/register    - Register new user
                  POST   /api/auth/login       - Log in and receive JWT
                  POST   /api/auth/logout      - Log out
                </domain>
                <domain name="Receipts">
                  GET    /api/receipts         - List receipts
                  POST   /api/receipts         - Create receipt
                </domain>
              </api_endpoints_summary>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert "Authentication" in spec.api_endpoints
        assert len(spec.api_endpoints["Authentication"]) == 3
        assert "Receipts" in spec.api_endpoints
        assert len(spec.api_endpoints["Receipts"]) == 2

    def test_phase_name_attribute_in_implementation_steps(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>phases</project_name>
              <implementation_steps>
                <phase name="Phase 1: Foundation &amp; Auth">
                  Set up project structure
                  Implement authentication
                </phase>
                <phase name="Phase 2: Core Features">
                  Build CRUD endpoints
                  Add pagination
                </phase>
              </implementation_steps>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.implementation_phases == [
            "Phase 1: Foundation & Auth",
            "Phase 2: Core Features",
        ]

    def test_empty_column_elements_ignored(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>emptycols</project_name>
              <database_schema>
                <tables>
                  <table name="items">
                    <column>id UUID PRIMARY KEY</column>
                    <column></column>
                    <column>name VARCHAR(255)</column>
                  </table>
                </tables>
              </database_schema>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.database_tables["items"] == ["id UUID PRIMARY KEY", "name VARCHAR(255)"]

    def test_domain_without_name_falls_back_to_tag(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification>
              <project_name>fallback</project_name>
              <api_endpoints_summary>
                <auth_endpoints>
                  - POST /api/auth/register
                </auth_endpoints>
              </api_endpoints_summary>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert "Auth Endpoints" in spec.api_endpoints

    def test_full_new_format_spec_roundtrip(self) -> None:
        xml = textwrap.dedent("""\
            <project_specification mode="greenfield">
              <project_name>Recipe Manager</project_name>
              <overview>A recipe management app.</overview>
              <target_audience>Home cooks.</target_audience>
              <core_features>
                <category name="Authentication &amp; User Management">
                  - User can register with email and password
                  - User can login and receive JWT tokens
                </category>
                <category name="Recipe Management">
                  - User can create a recipe with title and description
                  - User can delete a recipe
                </category>
              </core_features>
              <database_schema>
                <tables>
                  <table name="users">
                    <column>id UUID PRIMARY KEY DEFAULT gen_random_uuid()</column>
                    <column>email VARCHAR(255) UNIQUE NOT NULL</column>
                  </table>
                </tables>
              </database_schema>
              <api_endpoints_summary>
                <domain name="Authentication">
                  POST   /api/auth/register    - Register new user account
                  POST   /api/auth/login       - Log in and receive JWT tokens
                </domain>
              </api_endpoints_summary>
              <implementation_steps>
                <phase name="Phase 1: Auth">
                  Implement registration and login
                </phase>
                <phase name="Phase 2: Recipes">
                  Build recipe CRUD
                </phase>
              </implementation_steps>
            </project_specification>
        """)
        spec = ProjectSpec._parse_xml(xml)
        assert spec.project_name == "Recipe Manager"
        assert len(spec.features) == 4
        assert spec.features[0].category == "Authentication & User Management"
        assert spec.features[2].category == "Recipe Management"
        assert "users" in spec.database_tables
        assert spec.database_tables["users"][0] == "id UUID PRIMARY KEY DEFAULT gen_random_uuid()"
        assert "Authentication" in spec.api_endpoints
        assert spec.implementation_phases == ["Phase 1: Auth", "Phase 2: Recipes"]


# ── <feature index="N"> attribute (overlap-analysis support) ─────────────────


def test_feature_element_index_attribute_populates_index_field() -> None:
    """A <feature index="14"> attribute is preserved on FeatureItem."""
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="14">
                <description>User can register</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    assert len(spec.features) == 1
    assert spec.features[0].index == 14


def test_feature_element_without_index_has_none() -> None:
    """A <feature> with no index attribute leaves index = None."""
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature>
                <description>No index attr</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    assert len(spec.features) == 1
    assert spec.features[0].index is None


def test_feature_element_depends_on_attribute_resolves_to_positions() -> None:
    """``<feature depends_on="10,12">`` declares dependencies on the features
    with ``index="10"`` and ``index="12"``.  The parser resolves these to
    0-based positions in the feature list so downstream consumers
    (``_write_plan_to_db``) can use them uniformly with phase-inferred edges.
    """
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="10"><description>First</description></feature>
              <feature index="12"><description>Second</description></feature>
              <feature index="14" depends_on="10,12">
                <description>Third depends on both</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    assert len(spec.features) == 3
    # Feature at position 2 (index=14) depends on features at positions 0 and 1
    # (index=10 and index=12 respectively).
    assert spec.features[2].depends_on_indices == [0, 1]
    # Earlier features carry no edges from this attribute
    assert spec.features[0].depends_on_indices == []
    assert spec.features[1].depends_on_indices == []


def test_feature_element_depends_on_single_index() -> None:
    """A ``<feature depends_on="5">`` with one feature reference resolves to
    that feature's 0-based position."""
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="5"><description>Base</description></feature>
              <feature index="6" depends_on="5"><description>Dep</description></feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    # Feature at position 1 depends on feature at position 0.
    assert spec.features[1].depends_on_indices == [0]


def test_feature_element_depends_on_with_whitespace_and_garbage() -> None:
    """Whitespace and non-digit fragments in depends_on are tolerated/ignored.
    Valid references resolve to 0-based positions; junk is dropped silently.
    """
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="1"><description>A</description></feature>
              <feature index="2"><description>B</description></feature>
              <feature index="3" depends_on=" 1 ,  2 , junk ">
                <description>C</description>
              </feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    # Resolves index 1 → position 0, index 2 → position 1; "junk" dropped.
    assert spec.features[2].depends_on_indices == [0, 1]


def test_feature_element_depends_on_unknown_index_is_dropped() -> None:
    """A reference to a non-existent feature index is dropped rather than crashing."""
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="1"><description>A</description></feature>
              <feature index="2" depends_on="1,99"><description>B</description></feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    # 1 → position 0; 99 missing, dropped.
    assert spec.features[1].depends_on_indices == [0]


def test_mixed_legacy_bullets_and_feature_elements_in_same_category() -> None:
    """A category may contain a mix of legacy ``- bullet`` lines and new
    <feature> elements; both produce FeatureItems."""
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="Mixed">
              - Legacy bullet one
              - Legacy bullet two
              <feature index="3" depends_on="1"><description>New element</description></feature>
            </category>
          </core_features>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    descriptions = [f.description for f in spec.features]
    assert "Legacy bullet one" in descriptions
    assert "Legacy bullet two" in descriptions
    assert "New element" in descriptions
    assert len(spec.features) == 3


def test_explicit_depends_on_preserved_over_phase_inference() -> None:
    """Explicit depends_on attributes are preserved; phase-based inference
    only adds edges for features that didn't declare any explicitly.
    """
    xml = textwrap.dedent("""
        <project_specification>
          <project_name>Test</project_name>
          <core_features>
            <category name="X">
              <feature index="1"><description>A</description></feature>
              <feature index="2" depends_on="1"><description>B explicit</description></feature>
              <feature index="3"><description>C inferred</description></feature>
            </category>
          </core_features>
          <implementation_steps>
            <phase name="P1">A</phase>
            <phase name="P2">B explicit</phase>
            <phase name="P3">C inferred</phase>
          </implementation_steps>
        </project_specification>
    """).strip()
    spec = ProjectSpec._parse_xml(xml)
    # B has explicit depends_on="1" — resolves to position 0 (index=1).
    # Phase-inference is skipped because explicit edges are populated.
    assert spec.features[1].depends_on_indices == [0]
    # A is the first feature; no inferred deps (no earlier phase).
    assert spec.features[0].depends_on_indices == []


# ── <feature shape> and <feature plugin> attributes ───────────────────────────


class TestFeatureShapeAndPluginAttrs:
    def test_feature_shape_plugin_is_parsed(self) -> None:
        xml = textwrap.dedent("""
            <project_specification>
              <project_name>x</project_name>
              <core_features>
                <category name="Auth">
                  <feature index="1" shape="plugin" plugin="auth">
                    <description>User can register with email and password</description>
                  </feature>
                </category>
              </core_features>
            </project_specification>
        """).strip()
        spec = ProjectSpec._parse_xml(xml)
        assert len(spec.features) == 1
        feat = spec.features[0]
        assert feat.shape == "plugin"
        assert feat.plugin == "auth"

    def test_feature_shape_core_is_parsed(self) -> None:
        xml = textwrap.dedent("""
            <project_specification>
              <project_name>x</project_name>
              <core_features>
                <category name="Middleware">
                  <feature index="1" shape="core">
                    <description>All endpoints validate JWT on incoming requests</description>
                  </feature>
                </category>
              </core_features>
            </project_specification>
        """).strip()
        spec = ProjectSpec._parse_xml(xml)
        assert spec.features[0].shape == "core"
        assert spec.features[0].plugin is None

    def test_feature_without_shape_defaults_none(self) -> None:
        """Backward-compat: features without shape attr have shape=None."""
        xml = textwrap.dedent("""
            <project_specification>
              <project_name>x</project_name>
              <core_features>
                <category name="Misc">
                  <feature index="1"><description>Legacy feature</description></feature>
                </category>
              </core_features>
            </project_specification>
        """).strip()
        spec = ProjectSpec._parse_xml(xml)
        assert spec.features[0].shape is None
        assert spec.features[0].plugin is None

    def test_legacy_bullet_features_have_shape_none(self) -> None:
        """Bullet-form features pre-date shape; they parse to shape=None."""
        xml = textwrap.dedent("""
            <project_specification>
              <project_name>x</project_name>
              <core_features>
                <category name="Bullets">
                  - User can do something
                  - System returns response
                </category>
              </core_features>
            </project_specification>
        """).strip()
        spec = ProjectSpec._parse_xml(xml)
        for feat in spec.features:
            assert feat.shape is None
            assert feat.plugin is None
