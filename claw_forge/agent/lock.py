"""Agent lock file — prevents duplicate agents on the same project."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

LOCK_FILENAME = ".claw-forge.lock"


class AgentLockError(Exception):
    """Raised when an agent lock is already held."""
    pass


@contextmanager
def agent_lock(project_dir: Path):
    """Context manager that acquires an exclusive lock for a project directory.

    Creates a lock file containing the current PID. Raises AgentLockError if
    the lock file already exists. Cleans up the lock file on exit.
    """
    lock_file = project_dir / LOCK_FILENAME
    if lock_file.exists():
        pid = lock_file.read_text().strip()
        raise AgentLockError(
            f"Another agent is already running on this project (PID {pid}). "
            f"Delete {lock_file} to force-unlock."
        )
    lock_file.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock_file.unlink(missing_ok=True)
