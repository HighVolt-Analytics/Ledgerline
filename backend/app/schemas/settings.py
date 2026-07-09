"""Read-only app configuration for UI (Integrations / Settings screens)."""

from pydantic import BaseModel


class AppSettingsResponse(BaseModel):
    graph_mailbox: str
    graph_enabled: bool
    graph_poll_interval_minutes: int
    graph_folder_moves_enabled: bool
    graph_processed_folder: str
    graph_exceptions_folder: str
    blob_enabled: bool
    azure_storage_container: str
    azure_di_enabled: bool
    gemini_vision_available: bool = False
    azure_foundry_vision_available: bool = False
    default_document_ai_provider: str = "azure_di"
    azure_redis_enabled: bool
    appinsights_enabled: bool
    azure_location: str
    azure_webapp_url: str
    abn_validation_mode: str
    rule_book_config_path: str
    cors_origins: str
    whatsapp_configured: bool
    app_env: str = "development"
    payment_environment_label: str = "Development"
    public_app_base_url: str = ""
    public_api_base_url: str = ""
    stripe_mode: str = "sandbox"
    xero_configured: bool = False
    quickbooks_configured: bool = False
    stripe_global_payouts_enabled: bool = False
    stripe_global_payouts_access_status: str = "not_requested"
    stripe_payments_execution_enabled: bool = False
    stripe_live_payments_enabled: bool = False
    payment_manual_execution_enabled: bool = False
    payment_manual_execution_limit_usd: float = 1000.0
    payment_execution_disabled: bool = False
    use_field_registry: bool = False
