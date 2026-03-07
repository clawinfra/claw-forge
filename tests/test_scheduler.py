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

    def test_mark_completed_nonexistent_task_noop(self):
        """mark_completed with unknown task_id → no-op (41->exit branch)."""
        s = Scheduler()
        s.mark_completed("nonexistent-id")  # should not raise
        assert s._tasks == {}

    def test_mark_failed_nonexistent_task_noop(self):
        """mark_failed with unknown task_id → no-op."""
        s = Scheduler()
        s.mark_failed("nonexistent-id")
        assert s._tasks == {}

    def test_validate_no_cycles_with_external_dep(self):
        """Task depends on ID not in scheduler → dep skipped (line 81 continue)."""
        s = Scheduler()
        # task b depends on "external" which is not in the scheduler
        s.add_task(TaskNode("b", "coding", 1, ["external-task-not-here"]))
        # validate should not raise — external dep is skipped
        s.validate_no_cycles()

    def test_validate_no_cycles_already_visited_node_skipped(self):
        """When dep is added before dependency, outer loop skips already-BLACK tid (89->88)."""
        s = Scheduler()
        # b (depends on a) added FIRST → b comes first in dict iteration
        s.add_task(TaskNode("b", "code", 1, ["a"]))
        # a added second
        s.add_task(TaskNode("a", "init", 1, []))
        # dfs("b") will recursively call dfs("a"), setting color["a"]=BLACK.
        # When outer loop reaches "a", color["a"] != WHITE → 89->88 branch taken.
        s.validate_no_cycles()  # should not raise

    def test_execution_order_with_blocked_cycle_breaks(self):
        """All remaining tasks blocked (no progress) → break (line 106)."""
        s = Scheduler()
        # Task a depends on b, but b is not in the scheduler (so no wave can be formed)
        s.add_task(TaskNode("a", "coding", 1, ["b-not-here"]))
        waves = s.get_execution_order()
        # No waves can be formed since dep is missing → empty
        assert waves == []
