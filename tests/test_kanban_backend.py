"""Tests for the WebSocket ConnectionManager in claw_forge.state.service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from claw_forge.state.service import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws(*, fail_on_send: bool = False) -> Mock:
    """Create a mock WebSocket with async send_json."""
    ws = Mock()
    if fail_on_send:
        ws.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))
    else:
        ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# ConnectionManager.connect / disconnect
# ---------------------------------------------------------------------------


class TestConnectionManagerLifecycle:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_registers(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert mgr.active_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)
        assert mgr.active_count == 1
        mgr.disconnect(ws)
        assert mgr.active_count == 0

    def test_disconnect_unknown_ws_is_safe(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        # Should not raise even if ws was never registered
        mgr.disconnect(ws)
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_multiple_connections_tracked(self) -> None:
        mgr = ConnectionManager()
        ws1, ws2, ws3 = _make_ws(), _make_ws(), _make_ws()
        for ws in (ws1, ws2, ws3):
            await mgr.connect(ws)
        assert mgr.active_count == 3
        mgr.disconnect(ws2)
        assert mgr.active_count == 2


# ---------------------------------------------------------------------------
# ConnectionManager.broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_clients(self) -> None:
        mgr = ConnectionManager()
        ws1, ws2 = _make_ws(), _make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        payload: dict[str, Any] = {"type": "ping"}
        await mgr.broadcast(payload)

        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_broadcast_prunes_disconnected_clients(self) -> None:
        mgr = ConnectionManager()
        good_ws = _make_ws()
        bad_ws = _make_ws(fail_on_send=True)

        await mgr.connect(good_ws)
        await mgr.connect(bad_ws)
        assert mgr.active_count == 2

        await mgr.broadcast({"type": "test"})

        # Dead client should have been pruned
        assert mgr.active_count == 1
        good_ws.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_empty_pool_is_safe(self) -> None:
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast({"type": "noop"})

    @pytest.mark.asyncio
    async def test_broadcast_after_disconnect_skips_removed_client(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)
        mgr.disconnect(ws)

        await mgr.broadcast({"type": "test"})
        ws.send_json.assert_not_awaited()


# ---------------------------------------------------------------------------
# Typed broadcast helpers — event format
# ---------------------------------------------------------------------------


class TestTypedBroadcasts:
    @pytest.mark.asyncio
    async def test_feature_update_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        feature: dict[str, Any] = {"id": "abc-123", "status": "running"}
        await mgr.broadcast_feature_update(feature)

        ws.send_json.assert_awaited_once_with(
            {"type": "feature_update", "feature": feature}
        )

    @pytest.mark.asyncio
    async def test_pool_update_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        providers = [{"name": "p1", "health": "healthy"}]
        await mgr.broadcast_pool_update(providers)

        ws.send_json.assert_awaited_once_with(
            {"type": "pool_update", "providers": providers}
        )

    @pytest.mark.asyncio
    async def test_agent_started_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        await mgr.broadcast_agent_started(session_id="sess-1", feature_id=42)

        ws.send_json.assert_awaited_once_with(
            {"type": "agent_started", "session_id": "sess-1", "feature_id": 42}
        )

    @pytest.mark.asyncio
    async def test_agent_completed_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        await mgr.broadcast_agent_completed(
            session_id="sess-1", feature_id=42, passed=True
        )

        ws.send_json.assert_awaited_once_with(
            {
                "type": "agent_completed",
                "session_id": "sess-1",
                "feature_id": 42,
                "passed": True,
            }
        )

    @pytest.mark.asyncio
    async def test_cost_update_event_format(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        await mgr.broadcast_cost_update(total_cost=1.23, session_cost=0.05)

        ws.send_json.assert_awaited_once_with(
            {"type": "cost_update", "total_cost": 1.23, "session_cost": 0.05}
        )

    @pytest.mark.asyncio
    async def test_agent_completed_failed_flag(self) -> None:
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect(ws)

        await mgr.broadcast_agent_completed(
            session_id="sess-2", feature_id="feat-99", passed=False
        )

        call_args = ws.send_json.call_args[0][0]
        assert call_args["passed"] is False

    @pytest.mark.asyncio
    async def test_broadcast_reaches_multiple_clients_typed(self) -> None:
        """Typed broadcast helpers reach *all* clients, not just the first."""
        mgr = ConnectionManager()
        ws1, ws2 = _make_ws(), _make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast_cost_update(total_cost=5.0, session_cost=1.0)

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()
