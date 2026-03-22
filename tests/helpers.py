"""Shared test helpers for CLI and e2e tests."""

from __future__ import annotations

from typing import Any


class FakeHttpxResponse:
    """Minimal httpx.Response stand-in for CLI test mocks."""

    status_code = 200

    def __init__(self, data: Any) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._data


def make_fake_httpx_client(
    *,
    init_response: dict[str, Any],
    task_response: dict[str, Any],
) -> type:
    """Build a fake ``httpx.AsyncClient`` class for patching.

    Parameters
    ----------
    init_response:
        JSON returned by ``POST /sessions/init``.
    task_response:
        JSON returned by ``GET /tasks/{id}``.

    Returns
    -------
    A class that can replace ``httpx.AsyncClient`` in a ``patch()`` call.
    """

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            pass

        async def post(self, url: str, **kw: Any) -> FakeHttpxResponse:
            return FakeHttpxResponse(init_response)

        async def get(self, url: str, **kw: Any) -> FakeHttpxResponse:
            # GET /sessions/{id}/tasks returns a list; GET /tasks/{id} returns a dict
            if "/sessions/" in url and url.endswith("/tasks"):
                return FakeHttpxResponse([])
            return FakeHttpxResponse(task_response)

        async def patch(self, url: str, **kw: Any) -> FakeHttpxResponse:
            return FakeHttpxResponse({"ok": True})

    return _FakeClient
