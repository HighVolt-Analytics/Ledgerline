"""ASGI middleware: resolve tenant on every request."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import async_session_factory
from app.tenant_context import set_request_tenant_id
from app.tenant_isolation.resolution import TenantResolutionService


def _header(scope: Scope, name: str) -> str:
    name_b = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == name_b:
            return value.decode()
    return ""


class TenantContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        set_request_tenant_id(None)

        if not TenantResolutionService.should_skip_default(path):
            slug_hdr = _header(scope, "x-tenant-slug").strip().lower()
            query = scope.get("query_string", b"").decode()
            slug_q = ""
            for part in query.split("&"):
                if part.startswith("tenant="):
                    slug_q = part.split("=", 1)[-1].strip().lower()
                    break
            slug = slug_hdr or slug_q
            if slug:
                async with async_session_factory() as session:
                    tid = await TenantResolutionService.resolve_slug(session, slug)
                    if tid is not None:
                        set_request_tenant_id(tid)

        await self.app(scope, receive, send)
