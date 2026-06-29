"""Read-only application settings for frontend Integrations / Settings."""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.schemas.settings import AppSettingsResponse

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=ApiEnvelope[AppSettingsResponse])
async def get_app_settings() -> ApiEnvelope[AppSettingsResponse]:
    """Non-secret configuration safe to display in the UI."""
    s = get_settings()
    return ApiEnvelope(
        data=AppSettingsResponse(
            graph_mailbox=s.graph_mailbox,
            graph_enabled=s.graph_enabled,
            graph_poll_interval_minutes=s.graph_poll_interval_minutes,
            graph_folder_moves_enabled=s.graph_folder_moves_enabled,
            graph_processed_folder=s.graph_processed_folder,
            graph_exceptions_folder=s.graph_exceptions_folder,
            blob_enabled=s.blob_enabled,
            azure_storage_container=s.azure_storage_container,
            azure_di_enabled=s.azure_di_enabled,
            azure_postgres_enabled=s.azure_postgres_enabled,
            azure_redis_enabled=s.azure_redis_enabled,
            appinsights_enabled=s.appinsights_enabled,
            azure_location=s.azure_location,
            azure_webapp_url=s.azure_webapp_url,
            abn_validation_mode=s.abn_validation_mode,
            rule_book_config_path=s.rule_book_config_path,
            cors_origins=s.cors_origins,
            whatsapp_configured=s.whatsapp_configured,
            stripe_mode=s.stripe_mode,
            xero_configured=s.xero_configured,
            quickbooks_configured=s.quickbooks_configured,
            stripe_payments_execution_enabled=s.stripe_payment_execution_enabled,
            stripe_live_payments_enabled=s.stripe_live_payments_enabled,
            payment_manual_execution_enabled=s.payment_manual_execution_enabled,
            payment_manual_execution_limit_usd=s.payment_manual_execution_limit_usd,
            payment_execution_disabled=s.payment_execution_disabled,
        )
    )
