"""ASGI middleware for reverse-proxy path prefixes."""

from __future__ import annotations

from typing import Any


class ProxyPathPrefixMiddleware:
    """Strip a public path prefix before routing (e.g. /ledgerlink/api -> /api).

    Azure Front Door forwards the full public path to the backend LoadBalancer.
    FastAPI routes stay at /api/* and /health; this middleware removes the
    configured prefix from scope["path"] so existing routes match unchanged.
    """

    def __init__(self, app: Any, prefix: str) -> None:
        self.app = app
        self.prefix = prefix.rstrip("/") if prefix else ""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and self.prefix:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                scope["path"] = path[len(self.prefix) :] or "/"
                scope["root_path"] = f"{self.prefix}{scope.get('root_path', '')}"
        await self.app(scope, receive, send)
