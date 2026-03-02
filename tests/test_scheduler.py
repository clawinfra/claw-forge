"""Tests for dependency scheduler."""

import pytest

from claw_forge.state.scheduler import CycleDetectedError, Scheduler, TaskNode


class TestScheduler:
    def test_no_deps_all_ready(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "coding", 1, []))
        s.add_task(TaskNode("b", "testing", 2, []))
        ready = s.get_ready_tasks()
        assert len(ready) == 2
        assert ready[0].id == "b"  # higher priority first

    def test_dependency_ordering(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "init", 1, []))
        s.add_task(TaskNode("b", "coding", 1, ["a"]))
        ready = s.get_ready_tasks()
        assert [t.id for t in ready] == ["a"]
        s.mark_completed("a")
        ready = s.get_ready_tasks()
        assert [t.id for t in ready] == ["b"]

    def test_failed_dep_blocks_task(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "init", 1, []))
        s.add_task(TaskNode("b", "coding", 1, ["a"]))
        s.mark_failed("a")
        ready = s.get_ready_tasks()
        assert ready == []
        assert len(s.get_blocked_tasks()) == 1

    def test_cycle_detection(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "x", 1, ["b"]))
        s.add_task(TaskNode("b", "x", 1, ["a"]))
        with pytest.raises(CycleDetectedError):
            s.validate_no_cycles()

    def test_execution_waves(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "init", 1, []))
        s.add_task(TaskNode("b", "code", 1, []))
        s.add_task(TaskNode("c", "test", 1, ["a", "b"]))
        waves = s.get_execution_order()
        assert len(waves) == 2
        assert set(waves[0]) == {"a", "b"}
        assert waves[1] == ["c"]

    def test_remove_task(self):
        s = Scheduler()
        s.add_task(TaskNode("a", "x", 1, []))
        s.remove_task("a")
        assert s.get_ready_tasks() == []
