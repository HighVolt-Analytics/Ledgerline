"""ASGI middleware: clear request tenant context on every HTTP request."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.tenant_context import set_request_tenant_id


class TenantContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Tenant scope is set only after JWT validation in require_user — never from
        # unauthenticated headers, which would apply the wrong RLS during auth.
        set_request_tenant_id(None)
        await self.app(scope, receive, send)
