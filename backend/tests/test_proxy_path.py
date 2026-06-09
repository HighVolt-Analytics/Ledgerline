"""Tests for reverse-proxy path prefix (BASE_PATH / ROOT_PATH)."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import Settings
from app.middleware.proxy_path import ProxyPathPrefixMiddleware


async def _echo_path(request):
    return PlainTextResponse(request.url.path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("/ledgerlink", "/ledgerlink"),
        ("/ledgerlink/", "/ledgerlink"),
        ("ledgerlink", "/ledgerlink"),
        ("  /ledgerlink/  ", "/ledgerlink"),
    ],
)
def test_settings_normalize_root_path(raw: str, expected: str) -> None:
    settings = Settings(BASE_PATH=raw)
    assert settings.root_path == expected


@pytest.mark.asyncio
async def test_proxy_path_prefix_middleware_strips_prefix() -> None:
    inner = Starlette(routes=[Route("/api/settings", _echo_path)])
    app = ProxyPathPrefixMiddleware(inner, "/ledgerlink")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ledgerlink/api/settings")
        assert res.status_code == 200
        assert res.text == "/api/settings"

        res = await client.get("/api/settings")
        assert res.status_code == 200
        assert res.text == "/api/settings"


@pytest.mark.asyncio
async def test_proxy_path_prefix_strips_health_path() -> None:
    inner = Starlette(routes=[Route("/health", _echo_path)])
    app = ProxyPathPrefixMiddleware(inner, "/ledgerlink")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ledgerlink/health")
        assert res.status_code == 200
        assert res.text == "/health"


@pytest.mark.asyncio
async def test_proxy_path_prefix_empty_is_noop() -> None:
    inner = Starlette(routes=[Route("/api/settings", _echo_path)])
    app = ProxyPathPrefixMiddleware(inner, "")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/ledgerlink/api/settings")
        assert res.status_code == 404
