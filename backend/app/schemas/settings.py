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
    azure_postgres_enabled: bool
    azure_redis_enabled: bool
    appinsights_enabled: bool
    azure_location: str
    azure_webapp_url: str
    abn_validation_mode: str
    rule_book_config_path: str
    cors_origins: str
