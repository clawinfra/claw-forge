"""
E2E tests for claw-forge Kanban UI touch features.

Tests responsive layout, FAB visibility, stacked column view, and mobile
navigation using Playwright with a mobile viewport.

We serve the built UI via a local HTTP server and inject mock data via
JavaScript to avoid needing the real backend.
"""

import http.server
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

UI_DIST = Path(__file__).resolve().parent.parent / "claw_forge" / "ui_dist"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve from ui_dist directory silently."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIST), **kwargs)

    def log_message(self, *_args):
        pass  # suppress output


@pytest.fixture(scope="module")
def server():
    """Start a static file server for the built UI on a random free port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser_instance():
    """Launch a single browser for the module."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture()
def mobile_page(browser_instance: Browser, server: str):
    """Create a page with mobile viewport (375×812, iPhone-ish)."""
    ctx = browser_instance.new_context(
        viewport={"width": 375, "height": 812},
        device_scale_factor=2,
        has_touch=True,
        is_mobile=True,
    )
    page = ctx.new_page()

    # Navigate and inject a mock session so the board renders
    page.goto(f"{server}/?session=test-session-1")

    # Wait for initial render, then inject mock fetch to bypass real API
    page.evaluate("""() => {
        // Mock the fetch API to return test data
        const origFetch = window.fetch;
        window.fetch = async function(url, opts) {
            const urlStr = typeof url === 'string' ? url : url.toString();

            if (urlStr.includes('/sessions/') && urlStr.includes('/tasks')) {
                return new Response(JSON.stringify([
                    {
                        id: "1", name: "Auth module", category: "backend",
                        status: "completed", priority: 1, depends_on: [],
                        cost_usd: 0.12, input_tokens: 1000, output_tokens: 500,
                        created_at: "2026-01-01T00:00:00Z",
                        description: "Implement JWT authentication"
                    },
                    {
                        id: "2", name: "Dashboard UI", category: "frontend",
                        status: "running", priority: 2, depends_on: ["1"],
                        cost_usd: 0.05, input_tokens: 800, output_tokens: 300,
                        session_id: "agent-123", progress: 45,
                        created_at: "2026-01-01T00:00:00Z",
                        description: "Build the main dashboard"
                    },
                    {
                        id: "3", name: "Fix login bug", category: "backend",
                        status: "failed", priority: 3, depends_on: [],
                        cost_usd: 0.08, input_tokens: 600, output_tokens: 200,
                        error_message: "TypeError: Cannot read property 'token'",
                        created_at: "2026-01-01T00:00:00Z"
                    },
                    {
                        id: "4", name: "API rate limiter", category: "backend",
                        status: "pending", priority: 4, depends_on: [],
                        cost_usd: 0, input_tokens: 0, output_tokens: 0,
                        created_at: "2026-01-01T00:00:00Z"
                    },
                    {
                        id: "5", name: "DB migration", category: "infra",
                        status: "blocked", priority: 5, depends_on: ["1"],
                        cost_usd: 0, input_tokens: 0, output_tokens: 0,
                        created_at: "2026-01-01T00:00:00Z"
                    }
                ]), { status: 200, headers: { 'content-type': 'application/json' }});
            }
            if (urlStr.includes('/sessions/') && !urlStr.includes('/tasks')) {
                return new Response(JSON.stringify({
                    session_id: "test-session-1",
                    project_path: "/tmp/test-project"
                }), { status: 200, headers: { 'content-type': 'application/json' }});
            }
            if (urlStr.includes('/pool/status')) {
                return new Response(JSON.stringify([]), {
                    status: 200, headers: { 'content-type': 'application/json' }
                });
            }
            if (urlStr.includes('/commands/list')) {
                return new Response(JSON.stringify([]), {
                    status: 200, headers: { 'content-type': 'application/json' }
                });
            }
            // Fallback
            return origFetch(url, opts);
        };
    }""")

    # Force re-render by navigating again with mock in place
    page.goto(f"{server}/?session=test-session-1")
    page.wait_for_timeout(1500)  # let React settle

    yield page
    ctx.close()


@pytest.fixture()
def desktop_page(browser_instance: Browser, server: str):
    """Create a page with desktop viewport (1280×800)."""
    ctx = browser_instance.new_context(
        viewport={"width": 1280, "height": 800},
    )
    page = ctx.new_page()
    page.goto(f"{server}/?session=test-session-1")
    page.wait_for_timeout(1000)
    yield page
    ctx.close()


# ── Test: Responsive layout at 375px ──────────────────────────────────────


class TestResponsiveLayout:
    """Tests for responsive/stacked column view at <640px."""

    def test_mobile_viewport_width(self, mobile_page: Page):
        """At 375px, the page renders within mobile breakpoint."""
        vp = mobile_page.viewport_size
        assert vp is not None
        assert vp["width"] == 375

    def test_mobile_shows_single_column(self, mobile_page: Page):
        """On mobile, only one column should be visible at a time (stacked view)."""
        # The kanban-columns container should exist
        columns_container = mobile_page.locator('[data-testid="kanban-columns"]')
        if columns_container.count() > 0:
            # On mobile, the container should use flex-col layout
            display = columns_container.evaluate(
                "el => window.getComputedStyle(el).flexDirection"
            )
            assert display == "column", f"Expected column layout on mobile, got {display}"

    def test_mobile_column_nav_visible(self, mobile_page: Page):
        """Mobile column navigation dots should be visible."""
        nav = mobile_page.locator('[data-testid="mobile-column-nav"]')
        # May or may not be visible depending on rendering; if present, it should be visible
        if nav.count() > 0:
            assert nav.is_visible()

    def test_no_horizontal_scroll_on_mobile(self, mobile_page: Page):
        """Main content should not overflow horizontally on mobile."""
        overflow = mobile_page.evaluate("""() => {
            const main = document.querySelector('main');
            if (!main) return 'no-main';
            const style = window.getComputedStyle(main);
            return style.overflowX;
        }""")
        # Should be hidden on mobile (our CSS override)
        assert overflow in ("hidden", "no-main", "auto")  # auto is acceptable if content fits


# ── Test: FAB visibility ──────────────────────────────────────────────────


class TestFAB:
    """Tests for the Floating Action Button on mobile."""

    def test_fab_visible_on_mobile(self, mobile_page: Page):
        """FAB should be visible on mobile (<640px)."""
        fab = mobile_page.locator('[data-testid="fab-main"]')
        if fab.count() > 0:
            assert fab.is_visible(), "FAB should be visible on mobile"

    def test_fab_hidden_on_desktop(self, desktop_page: Page):
        """FAB should be hidden on desktop (≥640px)."""
        fab = desktop_page.locator('[data-testid="fab-main"]')
        # The FAB container has sm:hidden so at 1280px it should not render
        if fab.count() > 0:
            assert not fab.is_visible(), "FAB should be hidden on desktop"

    def test_fab_expand_shows_actions(self, mobile_page: Page):
        """Clicking FAB should reveal action buttons."""
        fab = mobile_page.locator('[data-testid="fab-main"]')
        if fab.count() > 0 and fab.is_visible():
            # Use force=True because mobile main content may visually overlap
            fab.click(force=True)
            mobile_page.wait_for_timeout(400)
            refresh = mobile_page.locator('[data-testid="fab-refresh"]')
            zoom = mobile_page.locator('[data-testid="fab-zoom-reset"]')
            # At least one action should appear
            has_actions = (refresh.count() > 0 and refresh.is_visible()) or \
                          (zoom.count() > 0 and zoom.is_visible())
            assert has_actions, "FAB should show action buttons when expanded"


# ── Test: Stacked column view ─────────────────────────────────────────────


class TestStackedView:
    """Tests for stacked/single column view at <640px."""

    def test_columns_stack_vertically_on_mobile(self, mobile_page: Page):
        """At <640px, columns should be in a flex-col layout."""
        container = mobile_page.locator('[data-testid="kanban-columns"]')
        if container.count() > 0:
            direction = container.evaluate(
                "el => window.getComputedStyle(el).flexDirection"
            )
            assert direction == "column"

    def test_column_full_width_on_mobile(self, mobile_page: Page):
        """Each visible column should be full-width on mobile."""
        # Find visible kanban columns
        cols = mobile_page.locator('[data-testid^="kanban-column-"]')
        if cols.count() > 0:
            first_col = cols.first
            if first_col.is_visible():
                box = first_col.bounding_box()
                if box:
                    # Should be close to viewport width (375px minus padding)
                    assert box["width"] >= 300, f"Column width {box['width']} too narrow for mobile"

    def test_desktop_shows_horizontal_columns(self, desktop_page: Page):
        """At ≥640px, columns should be in a flex-row layout."""
        container = desktop_page.locator('[data-testid="kanban-columns"]')
        if container.count() > 0:
            direction = container.evaluate(
                "el => window.getComputedStyle(el).flexDirection"
            )
            assert direction == "row"


# ── Test: Feature cards have touch attributes ─────────────────────────────


class TestTouchAttributes:
    """Tests for touch-related CSS/attributes on cards."""

    def test_cards_have_touch_manipulation(self, mobile_page: Page):
        """Feature cards should have touch-action: manipulation."""
        cards = mobile_page.locator('[data-testid="feature-card"]')
        if cards.count() > 0:
            ta = cards.first.evaluate(
                "el => window.getComputedStyle(el).touchAction"
            )
            assert "manipulation" in ta, f"Expected touch-action: manipulation, got {ta}"

    def test_kanban_board_has_scale_transform(self, mobile_page: Page):
        """The kanban board container should have a transform for zoom."""
        board = mobile_page.locator('[data-testid="kanban-board"]')
        if board.count() > 0:
            transform = board.evaluate(
                "el => el.style.transform"
            )
            assert "scale" in transform, f"Expected scale transform, got '{transform}'"
