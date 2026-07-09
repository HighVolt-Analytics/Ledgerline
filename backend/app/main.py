from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api import (
    accounting_integrations,
    approval_policy,
    approvals,
    billing,
    collections,
    customer_masters,
    customers,
    ledger_link,
    matrix,
    audit,
    auth,
    dashboard,
    notifications,
    dossiers,
    employee_masters,
    geo,
    invoices,
    mailboxes,
    oauth_auth,
    signup,
    tenants,
    tenant_members,
    platform,
    payments,
    pending_customers,
    pending_vendors,
    processing,
    purchases,
    reconciliation,
    registry,
    reports,
    rule_book,
    sales,
    settings as settings_api,
    stripe_webhooks,
    vault,
    vendor_masters,
    vendors,
    viber,
    whatsapp,
)
from app.api.deps import CorrelationIdMiddleware, require_super_admin, require_user
from app.config import get_settings
from app.database import async_session_factory
from app.middleware.proxy_path import ProxyPathPrefixMiddleware
from app.middleware.tenant_context_middleware import TenantContextMiddleware
from app.services.ingest.inline_mailbox_poller import (
    start_inline_mailbox_poller,
    stop_inline_mailbox_poller,
)
from app.services.rule_book.rule_book_save_buffer import flush_all_rule_book_save_buffers
from app.services.tenant.tenant_context_service import get_or_create_default_tenant, sync_env_mailbox
from app.services.tenant.tenant_module_service import require_module
from app.telemetry import setup_application_insights
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

_settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.auth_required:
        logger.warning(
            "auth_required_disabled",
            msg="AUTH_REQUIRED=false — API will reject unauthenticated tenant requests; "
            "do not disable in staging or production",
        )
    if settings.application_insights_runtime_enabled:
        setup_application_insights(settings.applicationinsights_connection_string)
    async with async_session_factory() as session:
        tenant = await get_or_create_default_tenant(session)
        await sync_env_mailbox(session, tenant.id)
        try:
            from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
            from app.services.rule_book.extraction_field_config_audit import (
                log_extraction_field_config_warnings,
            )

            config = await load_posting_config_for_tenant(session, tenant.id)
            log_extraction_field_config_warnings(config)
        except Exception as exc:
            logger.warning("extraction_field_config_startup_audit_failed", error=str(exc))
        await session.commit()
    logger.info("app_started")
    start_inline_mailbox_poller()
    yield
    await flush_all_rule_book_save_buffers()
    await stop_inline_mailbox_poller()
    logger.info("app_stopped")


app = FastAPI(
    title="Invoice Processing Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_settings.root_path,
)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Tenant-Id"],
)
if _settings.root_path:
    app.add_middleware(ProxyPathPrefixMiddleware, prefix=_settings.root_path)

app.include_router(auth.router, prefix="/api")
app.include_router(geo.router, prefix="/api")
app.include_router(oauth_auth.router, prefix="/api")
app.include_router(signup.router, prefix="/api")
# Stripe webhooks — no JWT.
app.include_router(stripe_webhooks.router, prefix="/api")
app.include_router(billing.public_router, prefix="/api")
# OAuth Microsoft redirect — no JWT (must be before authenticated mailboxes router).
app.include_router(mailboxes.oauth_public_router, prefix="/api")
# Stripe Connect OAuth callback — no JWT (must be before authenticated payments router).
app.include_router(payments.oauth_public_router, prefix="/api")
# Accounting OAuth callbacks (Xero, QuickBooks) — no JWT.
app.include_router(accounting_integrations.oauth_public_router, prefix="/api")
# Meta / WhatsApp OAuth callback and webhooks — no JWT.
# Paths: /webhook/meta, /auth/whatsapp/callback (Front Door routes /ledgerlink/webhook/* and /ledgerlink/auth/*).
app.include_router(whatsapp.public_router)
app.include_router(whatsapp.webhook_router)
app.include_router(viber.webhook_router)

_api_deps = [Depends(require_user)]


def _module_deps(key: str) -> list:
    return [*_api_deps, Depends(require_module(key))]


app.include_router(invoices.router, prefix="/api", dependencies=_api_deps)
app.include_router(dashboard.router, prefix="/api", dependencies=_api_deps)
app.include_router(notifications.router, prefix="/api", dependencies=_api_deps)
app.include_router(processing.router, prefix="/api", dependencies=_api_deps)
app.include_router(reconciliation.router, prefix="/api", dependencies=_api_deps)
app.include_router(audit.router, prefix="/api", dependencies=_api_deps)
app.include_router(vendors.router, prefix="/api", dependencies=_api_deps)
app.include_router(vendor_masters.router, prefix="/api", dependencies=_api_deps)
app.include_router(customer_masters.router, prefix="/api", dependencies=_api_deps)
app.include_router(customers.router, prefix="/api", dependencies=_module_deps("sales"))
app.include_router(employee_masters.router, prefix="/api", dependencies=_module_deps("team_expenses"))
app.include_router(pending_vendors.router, prefix="/api", dependencies=_api_deps)
app.include_router(pending_customers.router, prefix="/api", dependencies=_api_deps)
app.include_router(reports.router, prefix="/api", dependencies=_module_deps("reports"))
app.include_router(rule_book.router, prefix="/api", dependencies=_module_deps("rule_book"))
app.include_router(registry.router, prefix="/api", dependencies=_api_deps)
app.include_router(settings_api.router, prefix="/api", dependencies=_api_deps)
app.include_router(approvals.router, prefix="/api", dependencies=_api_deps)
app.include_router(approval_policy.router, prefix="/api", dependencies=_api_deps)
app.include_router(purchases.router, prefix="/api", dependencies=_module_deps("purchase"))
app.include_router(sales.router, prefix="/api", dependencies=_module_deps("sales"))
app.include_router(collections.router, prefix="/api", dependencies=_module_deps("sales"))
app.include_router(payments.router, prefix="/api", dependencies=_module_deps("payments"))
app.include_router(ledger_link.router, prefix="/api", dependencies=_module_deps("ledger_link"))
app.include_router(billing.router, prefix="/api", dependencies=_api_deps)
app.include_router(matrix.router, prefix="/api", dependencies=_api_deps)
app.include_router(dossiers.router, prefix="/api", dependencies=_module_deps("dossiers"))
app.include_router(mailboxes.router, prefix="/api", dependencies=_api_deps)
app.include_router(whatsapp.router, prefix="/api", dependencies=_api_deps)
app.include_router(accounting_integrations.router, prefix="/api", dependencies=_api_deps)
app.include_router(viber.router, prefix="/api", dependencies=_api_deps)
app.include_router(tenants.router, prefix="/api", dependencies=_api_deps)
app.include_router(tenant_members.router, prefix="/api", dependencies=_api_deps)
app.include_router(platform.router, prefix="/api", dependencies=[Depends(require_super_admin)])
app.include_router(vault.router, prefix="/api", dependencies=_module_deps("vault"))

_CONNECT_MAILBOX_HTML = (
    Path(__file__).resolve().parent / "static" / "connect_mailbox.html"
).read_text(encoding="utf-8")
_ACCEPT_INVITE_HTML = (
    Path(__file__).resolve().parent / "static" / "accept_invite.html"
).read_text(encoding="utf-8")


@app.get("/connect-mailbox", response_class=HTMLResponse, include_in_schema=False)
async def connect_mailbox_page() -> HTMLResponse:
    """Public mailbox invite landing page (works via ngrok on the API port)."""
    return HTMLResponse(content=_CONNECT_MAILBOX_HTML)


@app.get("/accept-invite", response_class=HTMLResponse, include_in_schema=False)
async def accept_invite_page() -> HTMLResponse:
    """Public tenant member invite landing page (works via ngrok on the API port)."""
    return HTMLResponse(content=_ACCEPT_INVITE_HTML)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
