"""Graph client response handling."""

import httpx
import pytest

from app.services import graph_client


def test_graph_request_accepts_empty_202(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        status_code = 202
        content = b""

        @property
        def text(self) -> str:
            return ""

        @property
        def is_error(self) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def request(self, *args, **kwargs) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(graph_client.httpx, "Client", _FakeClient)
    monkeypatch.setattr(graph_client, "get_application_access_token", lambda: "token")

    assert graph_client.graph_request("POST", "/users/me/sendMail") == {}
