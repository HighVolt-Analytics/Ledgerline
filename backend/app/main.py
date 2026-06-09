from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    approval_policy,
    approvals,
    matrix,
    audit,
    auth,
    dashboard,
    employee_masters,
    invoices,
    mailboxes,
    organisations,
    pending_vendors,
    processing,
    reconciliation,
    reports,
    rule_book,
    settings as settings_api,
    vault,
    vendor_masters,
    vendors,
)
from app.api.deps import CorrelationIdMiddleware, require_user
from app.config import get_settings
from app.database import async_session_factory
from app.services.org_context import get_or_create_default_org, sync_env_mailbox
from app.telemetry import setup_application_insights
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


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
    yield
    logger.info("app_stopped")


app = FastAPI(title="Invoice Processing Pipeline", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)

app.include_router(auth.router, prefix="/api")

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
app.include_router(matrix.router, prefix="/api", dependencies=_api_deps)
app.include_router(mailboxes.router, prefix="/api", dependencies=_api_deps)
app.include_router(organisations.router, prefix="/api", dependencies=_api_deps)
app.include_router(vault.router, prefix="/api", dependencies=_api_deps)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
