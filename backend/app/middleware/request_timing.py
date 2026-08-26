"""Pure ASGI request timing — duration_ms in JSON logs + X-Process-Time header.

Starlette BaseHTTPMiddleware is not used (it can deadlock under load).
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.utils.logger import get_logger

logger = get_logger(__name__)

_SKIP_LOG_PATHS = frozenset({"/health", "/ready"})


class RequestTimingMiddleware:
    """Record wall-clock time for each HTTP request.

    X-Process-Time is milliseconds to first byte (headers). The http_request
    log uses duration_ms until the ASGI call returns (includes body send).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 0
        correlation_id = ""

        async def send_with_timing(message: Message) -> None:
            nonlocal status_code, correlation_id
            if message["type"] == "http.response.start":
                status_code = int(message.get("status") or 0)
                ttfb_ms = (time.perf_counter() - start) * 1000.0
                raw_headers = list(message.get("headers") or [])
                for key, value in raw_headers:
                    if key == b"x-correlation-id":
                        correlation_id = value.decode("latin-1")
                        break
                raw_headers.append(
                    (b"x-process-time", f"{ttfb_ms:.1f}".encode("latin-1"))
                )
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            path = str(scope.get("path") or "")
            method = str(scope.get("method") or "")
            if method == "OPTIONS" or path in _SKIP_LOG_PATHS:
                return
            duration_ms = round((time.perf_counter() - start) * 1000.0, 1)
            raw_qs = scope.get("query_string") or b""
            query = raw_qs.decode("latin-1") if raw_qs else ""
            logger.info(
                "http_request",
                method=method,
                path=path,
                query=query or None,
                status=status_code,
                duration_ms=duration_ms,
                correlation_id=correlation_id or None,
            )
