"""Dependency-aware task scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskNode:
    """Lightweight task representation for scheduling."""

    id: str
    plugin_name: str
    priority: int
    depends_on: list[str]
    status: str = "pending"
    category: str = ""
    steps: list[str] = field(default_factory=list)
    description: str = ""
    merged_to_target_branch: bool = True  # gate: dep not satisfied until merged
    touches_files: list[str] = field(default_factory=list)
    # True when a feature branch with committed work already exists for this task,
    # so picking it lets the agent resume rather than start from scratch.
    resumable: bool = False


class CycleDetectedError(Exception):
    """Circular dependency in task graph."""


class Scheduler:
    """Topological scheduler with priority ordering within each level.

    Determines which tasks are ready to run based on dependency completion.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskNode] = {}

    def add_task(self, task: TaskNode) -> None:
        self._tasks[task.id] = task

    def remove_task(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def mark_completed(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = "completed"

    def mark_failed(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = "failed"

    def get_ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed AND merged, sorted by priority."""
        # A dep is satisfied when status == completed AND merged_to_target_branch is True.
        satisfied: set[str] = {
            tid for tid, t in self._tasks.items()
            if t.status == "completed" and t.merged_to_target_branch
        }
        failed = {tid for tid, t in self._tasks.items() if t.status == "failed"}

        ready: list[TaskNode] = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            # Deps absent from this scheduler were completed in a prior dispatch cycle.
            known_failed = {dep for dep in task.depends_on if dep in failed}
            if known_failed:
                # Dependency failed — mark as blocked
                task.status = "blocked"
                continue
            # A dep is satisfied when it is completed+merged in this cycle OR not
            # present in this scheduler at all (finished before this dispatch cycle).
            unsatisfied = {
                dep for dep in task.depends_on
                if dep in self._tasks and dep not in satisfied
            }
            if not unsatisfied:
                ready.append(task)

        # Sort: priority desc dominates; among same priority, prefer resumable
        # (a task with committed work on a feature branch wins the tie so the
        # agent resumes rather than starts from scratch).
        return sorted(ready, key=lambda t: (-t.priority, 0 if t.resumable else 1))

    def get_blocked_tasks(self) -> list[TaskNode]:
        return [t for t in self._tasks.values() if t.status == "blocked"]

    def validate_no_cycles(self) -> None:
        """Detect cycles using DFS."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {tid: WHITE for tid in self._tasks}

        def dfs(tid: str) -> None:
            color[tid] = GRAY
            task = self._tasks.get(tid)
            if task:
                for dep in task.depends_on:
                    if dep not in color:
                        continue
                    if color[dep] == GRAY:
                        raise CycleDetectedError(f"Cycle detected involving task {dep}")
                    if color[dep] == WHITE:
                        dfs(dep)
            color[tid] = BLACK

        for tid in self._tasks:
            if color[tid] == WHITE:
                dfs(tid)

    def get_execution_order(self) -> list[list[str]]:
        """Return tasks grouped by execution wave (parallelizable within each wave).

        Dependency IDs absent from this scheduler are treated as already satisfied —
        they were completed in a prior dispatch cycle (e.g. after pause/resume).
        """
        self.validate_no_cycles()
        waves: list[list[str]] = []
        # Tasks already completed-and-merged before this dispatch cycle.
        completed: set[str] = {
            tid for tid, t in self._tasks.items()
            if t.status == "completed" and t.merged_to_target_branch
        }
        remaining = {tid for tid, t in self._tasks.items() if t.status == "pending"}

        while remaining:
            wave: list[str] = []
            for tid in list(remaining):
                task = self._tasks[tid]
                # A dep is satisfied when completed in this cycle OR absent from this
                # scheduler (finished before this dispatch cycle, e.g. after resume).
                unsatisfied = {
                    dep for dep in task.depends_on
                    if dep in self._tasks and dep not in completed
                }
                if not unsatisfied:
                    wave.append(tid)
            if not wave:
                break  # Blocked tasks
            wave.sort(key=lambda t: self._tasks[t].priority, reverse=True)
            waves.append(wave)
            completed.update(wave)
            remaining -= set(wave)

        return waves
