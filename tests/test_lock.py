"""Tests for claw_forge.agent.lock."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from claw_forge.agent.lock import LOCK_FILENAME, AgentLockError, agent_lock


class TestAgentLock:
    def test_creates_lock_file(self, tmp_path: Path):
        with agent_lock(tmp_path):
            lock_file = tmp_path / LOCK_FILENAME
            assert lock_file.exists()

    def test_lock_file_contains_pid(self, tmp_path: Path):
        with agent_lock(tmp_path):
            lock_file = tmp_path / LOCK_FILENAME
            pid = lock_file.read_text().strip()
            assert pid == str(os.getpid())

    def test_lock_file_removed_on_exit(self, tmp_path: Path):
        with agent_lock(tmp_path):
            pass
        lock_file = tmp_path / LOCK_FILENAME
        assert not lock_file.exists()

    def test_raises_when_lock_already_held(self, tmp_path: Path):
        lock_file = tmp_path / LOCK_FILENAME
        lock_file.write_text("99999")  # Simulate existing lock
        with pytest.raises(AgentLockError) as exc_info:
            with agent_lock(tmp_path):
                pass
        assert "99999" in str(exc_info.value)
        assert "force-unlock" in str(exc_info.value)

    def test_lock_file_removed_on_exception_inside_context(self, tmp_path: Path):
        with pytest.raises(ValueError):
            with agent_lock(tmp_path):
                raise ValueError("something went wrong")
        lock_file = tmp_path / LOCK_FILENAME
        assert not lock_file.exists()

    def test_error_message_includes_lock_path(self, tmp_path: Path):
        lock_file = tmp_path / LOCK_FILENAME
        lock_file.write_text("12345")
        with pytest.raises(AgentLockError) as exc_info:
            with agent_lock(tmp_path):
                pass
        assert str(lock_file) in str(exc_info.value)

    def test_sequential_locks_work(self, tmp_path: Path):
        """Two sequential locks on the same dir should both succeed."""
        with agent_lock(tmp_path):
            pass
        with agent_lock(tmp_path):
            pass
        assert not (tmp_path / LOCK_FILENAME).exists()
