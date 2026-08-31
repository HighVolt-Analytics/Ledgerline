from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api import (
    accounting_integrations,
    approval_policy,
    approvals,
    bank_feeds,
    billing,
    collections,
    customer_masters,
    customers,
    department_budgets,
    ledger_link,
    master_confirm,
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
    meta,
    signup,
    tenants,
    tenant_members,
    platform,
    payments,
    pending_customers,
    pending_vendors,
    paypal_payments,
    paypal_webhooks,
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
    xero_webhooks,
    xero_refinement,
    xero_master_data,
    xero_export_pipeline,
)
from app.api.deps import CorrelationIdMiddleware, require_super_admin, require_user
from app.config import get_settings
from app.database import async_session_factory
from app.middleware.proxy_path import ProxyPathPrefixMiddleware
from app.middleware.request_timing import RequestTimingMiddleware
from app.middleware.tenant_context_middleware import TenantContextMiddleware
from app.services.ingest.inline_mailbox_poller import (
    start_inline_mailbox_poller,
    stop_inline_mailbox_poller,
)
from app.integrations.xero.background_sync import (
    start_xero_background_sync,
    stop_xero_background_sync,
)
from app.services.rule_book.rule_book_save_buffer import flush_all_rule_book_save_buffers
from app.services.integration.accounting_integration_service import XeroNotReadyError
from app.integrations.xero.mapping import XeroMappingValidationError
from app.services.shared.public_app_url import build_oauth_frontend_path
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
            msg="AUTH_REQUIRED=false â€” API will reject unauthenticated tenant requests; "
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
    start_xero_background_sync()
    yield
    await flush_all_rule_book_save_buffers()
    await stop_inline_mailbox_poller()
    await stop_xero_background_sync()
    logger.info("app_stopped")


app = FastAPI(
    title="Invoice Processing Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_settings.root_path,
)


@app.exception_handler(XeroMappingValidationError)
async def xero_mapping_validation_handler(
    _request: Request,
    exc: XeroMappingValidationError,
) -> JSONResponse:
    return JSONResponse(status_code=422, content=exc.result.to_dict())


@app.exception_handler(XeroNotReadyError)
async def xero_not_ready_handler(
    _request: Request,
    exc: XeroNotReadyError,
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Process-Time", "X-Tenant-Id"],
)
if _settings.root_path:
    app.add_middleware(ProxyPathPrefixMiddleware, prefix=_settings.root_path)
# Gzip behind Front Door/nginx. Skip local Vite — compressed API bodies plus
# --reload ECONNRESET leave the SPA unable to parse /api/auth/me on hard refresh.
if _settings.app_env.strip().lower() in {
    "production",
    "prod",
    "preview",
    "staging",
    "stage",
    "ledgerlink",
}:
    app.add_middleware(GZipMiddleware, minimum_size=500)
# Outermost so duration_ms includes gzip. Pure ASGI (not BaseHTTPMiddleware).
app.add_middleware(RequestTimingMiddleware)

app.include_router(auth.router, prefix="/api")
app.include_router(master_confirm.router, prefix="/api")
app.include_router(geo.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(oauth_auth.router, prefix="/api")
app.include_router(signup.router, prefix="/api")
# Stripe webhooks — no JWT.
app.include_router(stripe_webhooks.router, prefix="/api")
# PayPal webhooks — no JWT.
app.include_router(paypal_webhooks.router, prefix="/api")
# Xero webhooks — no JWT.
app.include_router(xero_webhooks.router, prefix="/api")
app.include_router(billing.public_router, prefix="/api")
# OAuth Microsoft redirect â€” no JWT (must be before authenticated mailboxes router).
app.include_router(mailboxes.oauth_public_router, prefix="/api")
# Stripe Connect OAuth callback â€” no JWT (must be before authenticated payments router).
app.include_router(payments.oauth_public_router, prefix="/api")
# PayPal Connect OAuth callback — no JWT.
app.include_router(paypal_payments.oauth_public_router, prefix="/api")
# Accounting OAuth callbacks (Xero, QuickBooks) â€” no JWT.
app.include_router(accounting_integrations.oauth_public_router, prefix="/api")
# Meta / WhatsApp OAuth callback and webhooks â€” no JWT.
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
app.include_router(department_budgets.router, prefix="/api", dependencies=_module_deps("team_expenses"))
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
app.include_router(bank_feeds.router, prefix="/api", dependencies=_module_deps("bank_feeds"))
app.include_router(paypal_payments.router, prefix="/api", dependencies=_module_deps("payments"))
app.include_router(ledger_link.router, prefix="/api", dependencies=_module_deps("ledger_link"))
app.include_router(billing.router, prefix="/api", dependencies=_api_deps)
app.include_router(matrix.router, prefix="/api", dependencies=_api_deps)
app.include_router(dossiers.router, prefix="/api", dependencies=_api_deps)
app.include_router(mailboxes.router, prefix="/api", dependencies=_api_deps)
app.include_router(whatsapp.router, prefix="/api", dependencies=_api_deps)
app.include_router(accounting_integrations.router, prefix="/api", dependencies=_api_deps)
app.include_router(xero_refinement.router, prefix="/api", dependencies=_api_deps)
app.include_router(xero_master_data.router, prefix="/api", dependencies=_api_deps)
app.include_router(xero_export_pipeline.router, prefix="/api", dependencies=_api_deps)
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
_CONFIRM_MASTER_HTML = (
    Path(__file__).resolve().parent / "static" / "confirm_master.html"
).read_text(encoding="utf-8")


@app.get("/connect-mailbox", response_class=HTMLResponse, include_in_schema=False)
async def connect_mailbox_page() -> HTMLResponse:
    """Public mailbox invite landing page (works via ngrok on the API port)."""
    return HTMLResponse(content=_CONNECT_MAILBOX_HTML)


@app.get("/accept-invite", response_class=HTMLResponse, include_in_schema=False)
async def accept_invite_page() -> HTMLResponse:
    """Public tenant member invite landing page (works via ngrok on the API port)."""
    return HTMLResponse(content=_ACCEPT_INVITE_HTML)


@app.get("/confirm-master", response_class=HTMLResponse, include_in_schema=False)
async def confirm_master_page() -> HTMLResponse:
    """Public vendor/employee master confirmation page."""
    return HTMLResponse(content=_CONFIRM_MASTER_HTML)


@app.get("/signup", include_in_schema=False)
@app.get("/start", include_in_schema=False)
@app.get("/get-started", include_in_schema=False)
@app.get("/register", include_in_schema=False)
@app.get("/setup", include_in_schema=False)
@app.get("/billing", include_in_schema=False)
async def redirect_frontend_app_routes(request: Request) -> RedirectResponse:
    """Send SPA routes to the React dev server when ngrok tunnels to the API."""
    target = build_oauth_frontend_path(request.url.path)
    if request.url.query:
        separator = "&" if "?" in target else "?"
        target = f"{target}{separator}{request.url.query}"
    return RedirectResponse(url=target, status_code=307)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

