from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api import (
    approval_policy,
    approvals,
    billing,
    ledger_link,
    matrix,
    audit,
    auth,
    dashboard,
    dossiers,
    employee_masters,
    invoices,
    mailboxes,
    organisations,
    payments,
    pending_vendors,
    processing,
    purchases,
    reconciliation,
    reports,
    rule_book,
    settings as settings_api,
    vault,
    vendor_masters,
    vendors,
    whatsapp,
)
from app.api.deps import CorrelationIdMiddleware, require_user
from app.config import get_settings
from app.database import async_session_factory
from app.middleware.proxy_path import ProxyPathPrefixMiddleware
from app.services.inline_mailbox_poller import (
    start_inline_mailbox_poller,
    stop_inline_mailbox_poller,
)
from app.services.org_context import get_or_create_default_org, sync_env_mailbox
from app.telemetry import setup_application_insights
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

_settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.application_insights_runtime_enabled:
        setup_application_insights(settings.applicationinsights_connection_string)
    async with async_session_factory() as session:
        org = await get_or_create_default_org(session)
        await sync_env_mailbox(session, org.id)
        await session.commit()
    logger.info("app_started")
    start_inline_mailbox_poller()
    yield
    await stop_inline_mailbox_poller()
    logger.info("app_stopped")


app = FastAPI(
    title="Invoice Processing Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_settings.root_path,
)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)
if _settings.root_path:
    app.add_middleware(ProxyPathPrefixMiddleware, prefix=_settings.root_path)

app.include_router(auth.router, prefix="/api")
# OAuth Microsoft redirect — no JWT (must be before authenticated mailboxes router).
app.include_router(mailboxes.oauth_public_router, prefix="/api")
# Meta / WhatsApp OAuth callback and webhooks — no JWT.
# Paths: /webhook/meta, /auth/whatsapp/callback (Front Door routes /ledgerlink/webhook/* and /ledgerlink/auth/*).
app.include_router(whatsapp.public_router)
app.include_router(whatsapp.webhook_router)

_api_deps = [Depends(require_user)]
app.include_router(invoices.router, prefix="/api", dependencies=_api_deps)
app.include_router(dashboard.router, prefix="/api", dependencies=_api_deps)
app.include_router(processing.router, prefix="/api", dependencies=_api_deps)
app.include_router(reconciliation.router, prefix="/api", dependencies=_api_deps)
app.include_router(audit.router, prefix="/api", dependencies=_api_deps)
app.include_router(vendors.router, prefix="/api", dependencies=_api_deps)
app.include_router(vendor_masters.router, prefix="/api", dependencies=_api_deps)
app.include_router(employee_masters.router, prefix="/api", dependencies=_api_deps)
app.include_router(pending_vendors.router, prefix="/api", dependencies=_api_deps)
app.include_router(reports.router, prefix="/api", dependencies=_api_deps)
app.include_router(rule_book.router, prefix="/api", dependencies=_api_deps)
app.include_router(settings_api.router, prefix="/api", dependencies=_api_deps)
app.include_router(approvals.router, prefix="/api", dependencies=_api_deps)
app.include_router(approval_policy.router, prefix="/api", dependencies=_api_deps)
app.include_router(purchases.router, prefix="/api", dependencies=_api_deps)
app.include_router(payments.router, prefix="/api", dependencies=_api_deps)
app.include_router(ledger_link.router, prefix="/api", dependencies=_api_deps)
app.include_router(billing.router, prefix="/api", dependencies=_api_deps)
app.include_router(matrix.router, prefix="/api", dependencies=_api_deps)
app.include_router(dossiers.router, prefix="/api", dependencies=_api_deps)
app.include_router(mailboxes.router, prefix="/api", dependencies=_api_deps)
app.include_router(whatsapp.router, prefix="/api", dependencies=_api_deps)
app.include_router(organisations.router, prefix="/api", dependencies=_api_deps)
app.include_router(vault.router, prefix="/api", dependencies=_api_deps)

_CONNECT_MAILBOX_HTML = (
    Path(__file__).resolve().parent / "static" / "connect_mailbox.html"
).read_text(encoding="utf-8")


@app.get("/connect-mailbox", response_class=HTMLResponse, include_in_schema=False)
async def connect_mailbox_page() -> HTMLResponse:
    """Public invite landing page (works via ngrok on the API port)."""
    return HTMLResponse(content=_CONNECT_MAILBOX_HTML)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
