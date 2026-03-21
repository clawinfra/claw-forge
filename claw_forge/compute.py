"""Opt-in CPU offloading via ProcessPoolExecutor."""
from __future__ import annotations

import asyncio
import atexit
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import wraps
from typing import Any, TypeVar

_pool: ProcessPoolExecutor | None = None
_F = TypeVar("_F", bound=Callable[..., Any])


def get_pool() -> ProcessPoolExecutor:
    """Lazy-init a process pool capped at 4 workers."""
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=min(os.cpu_count() or 2, 4))
        atexit.register(shutdown_pool)
    return _pool


def shutdown_pool() -> None:
    """Shut down the process pool. Idempotent."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False)
        _pool = None


def _run_by_name(module: str, qualname: str, *args: Any) -> Any:
    """Resolve a function by module + qualname and call it.

    This indirection ensures the pickled payload contains only strings
    and args — avoiding the "not the same object" pickling error that
    occurs when @wraps makes the wrapper shadow the original function's
    __qualname__.
    """
    import importlib
    mod = importlib.import_module(module)
    obj: Any = mod
    for attr in qualname.split("."):
        obj = getattr(obj, attr)
    # The resolved name is the *wrapper*; call __wrapped__ to get the original.
    original = getattr(obj, "__wrapped__", obj)
    return original(*args)


def offload_heavy(fn: _F) -> _F:
    """Decorator: run a sync function in the process pool.

    The decorated function becomes a coroutine. Requirements:
    - Must be a module-level function (picklable)
    - Arguments and return value must be picklable
    - Must be pure (no shared mutable state)
    """
    mod_name = fn.__module__
    qual_name = fn.__qualname__

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            get_pool(), _run_by_name, mod_name, qual_name, *args,
        )

    return wrapper  # type: ignore[return-value]
