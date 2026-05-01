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

    def test_execution_order_missing_dep_treated_as_satisfied(self):
        """Deps absent from the scheduler are treated as already completed.

        This is the resume-after-pause scenario: tasks completed in a prior
        dispatch cycle are removed from the re-dispatch list, so a pending task
        whose dep is "missing" should still be schedulable.
        """
        s = Scheduler()
        # Task a depends on b, but b is not in this scheduler (completed earlier).
        s.add_task(TaskNode("a", "coding", 1, ["b-completed-earlier"]))
        waves = s.get_execution_order()
        # a should be scheduled because its dep is considered satisfied.
        assert waves == [["a"]]

    def test_execution_order_with_blocked_cycle_breaks(self):
        """All remaining tasks blocked (circular / unsatisfiable) → break."""
        s = Scheduler()
        # Both tasks are in the scheduler and depend on each other (cycle-like
        # deadlock without an actual cycle in validate_no_cycles sense).
        s.add_task(TaskNode("a", "coding", 1, ["b"]))
        s.add_task(TaskNode("b", "coding", 1, ["a"]))
        # validate_no_cycles detects this as a cycle — it will raise.
        # Use a simpler non-cycle deadlock: both tasks depend on a third that
        # is in the scheduler but not pending (stuck as running, never completes).
        s2 = Scheduler()
        stuck = TaskNode("blocker", "coding", 1, [])
        stuck.status = "running"  # not pending, so never completes in this cycle
        s2.add_task(stuck)
        s2.add_task(TaskNode("a", "coding", 1, ["blocker"]))
        waves = s2.get_execution_order()
        # "a" cannot run because "blocker" is in the scheduler but not completed.
        assert waves == []

    def test_completed_dep_not_merged_to_main_keeps_child_blocked(self):
        """A child whose parent is completed but merged_to_main=False stays blocked."""
        s = Scheduler()
        parent = TaskNode(
            id="parent", plugin_name="coding", priority=0, depends_on=[],
            status="completed", merged_to_main=False,
        )
        child = TaskNode(
            id="child", plugin_name="coding", priority=0, depends_on=["parent"],
            status="pending",
        )
        s.add_task(parent)
        s.add_task(child)
        assert s.get_ready_tasks() == []  # child stays blocked

    def test_completed_dep_with_merged_to_main_unblocks_child(self):
        """A child whose parent is completed AND merged_to_main is unblocked."""
        s = Scheduler()
        parent = TaskNode(
            id="parent", plugin_name="coding", priority=0, depends_on=[],
            status="completed", merged_to_main=True,
        )
        child = TaskNode(
            id="child", plugin_name="coding", priority=0, depends_on=["parent"],
            status="pending",
        )
        s.add_task(parent)
        s.add_task(child)
        assert [t.id for t in s.get_ready_tasks()] == ["child"]
