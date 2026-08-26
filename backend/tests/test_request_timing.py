"""RequestTimingMiddleware sets X-Process-Time without BaseHTTPMiddleware."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.middleware.request_timing import RequestTimingMiddleware


async def _ok(_request):
    return JSONResponse({"ok": True})


@pytest.mark.asyncio
async def test_request_timing_sets_process_time_header() -> None:
    inner = Starlette(routes=[Route("/health", _ok), Route("/api/ping", _ok)])
    app = RequestTimingMiddleware(inner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        health_ms = float(health.headers["x-process-time"])
        assert health_ms >= 0

        ping = await client.get("/api/ping")
        assert ping.status_code == 200
        ping_ms = float(ping.headers["x-process-time"])
        assert ping_ms >= 0
