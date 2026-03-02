"""Dependency-aware task scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TaskNode:
    """Lightweight task representation for scheduling."""

    id: str
    plugin_name: str
    priority: int
    depends_on: list[str]
    status: str = "pending"


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
        """Return tasks whose dependencies are all completed, sorted by priority."""
        completed = {tid for tid, t in self._tasks.items() if t.status == "completed"}
        failed = {tid for tid, t in self._tasks.items() if t.status == "failed"}

        ready: list[TaskNode] = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            deps = set(task.depends_on)
            if deps & failed:
                # Dependency failed — mark as blocked
                task.status = "blocked"
                continue
            if deps <= completed:
                ready.append(task)

        return sorted(ready, key=lambda t: t.priority, reverse=True)

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
        """Return tasks grouped by execution wave (parallelizable within each wave)."""
        self.validate_no_cycles()
        waves: list[list[str]] = []
        completed: set[str] = set()
        remaining = {tid for tid, t in self._tasks.items() if t.status == "pending"}

        while remaining:
            wave: list[str] = []
            for tid in list(remaining):
                task = self._tasks[tid]
                if set(task.depends_on) <= completed:
                    wave.append(tid)
            if not wave:
                break  # Blocked tasks
            wave.sort(key=lambda t: self._tasks[t].priority, reverse=True)
            waves.append(wave)
            completed.update(wave)
            remaining -= set(wave)

        return waves
