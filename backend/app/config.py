"""Load settings from environment variables."""

import os
from functools import lru_cache
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.azure_env import (
    build_postgres_url,
    build_redis_url,
    normalize_database_url,
    normalize_redis_url,
)


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://invoice:invoice@localhost:5432/invoice_db"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    upload_dir: str = "./uploads"
    rule_book_config_path: str = Field(
        default="./app/rule_book_config.json",
        validation_alias=AliasChoices("RULE_BOOK_CONFIG_PATH", "RULE_BOOK_PATH"),
    )
    chart_of_accounts_path: str = "./app/chart_of_accounts.json"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@invoice-pipeline.local"

    # Azure resource metadata (optional; for docs / UI)
    azure_location: str = Field(default="", validation_alias="AZURE_LOCATION")
    azure_resource_group: str = Field(default="", validation_alias="AZURE_RESOURCE_GROUP")
    azure_webapp_url: str = Field(default="", validation_alias="AZURE_WEBAPP_URL")

    # Azure PostgreSQL components (used when POSTGRES_HOST is set)
    postgres_host: str = Field(default="", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(default="", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")

    # Azure Redis components (used when REDIS_HOST is set)
    redis_host: str = Field(default="", validation_alias="REDIS_HOST")
    redis_ssl_port: int = Field(default=6380, validation_alias="REDIS_SSL_PORT")
    redis_password: str = Field(default="", validation_alias="REDIS_PASSWORD")

    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    graph_mailbox: str = ""
    graph_max_messages: int = 50
    graph_poll_interval_minutes: int = Field(default=2, ge=1, le=60)
    graph_folder_moves_enabled: bool = True
    graph_processed_folder: str = "Processed"
    graph_exceptions_folder: str = "Exceptions"

    azure_di_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_DI_ENDPOINT",
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        ),
    )
    azure_di_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_DI_KEY",
            "AZURE_DOCUMENT_INTELLIGENCE_KEY",
        ),
    )
    azure_di_model_id: str = "prebuilt-invoice"
    parse_min_text_chars: int = 200
    abn_validation_mode: str = Field(default="format")
    duplicate_invoice_check_enabled: bool = False

    azure_storage_connection_string: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_STORAGE_CONNECTION",
        ),
    )
    azure_storage_container: str = "invoices"
    blob_auto_relocate_unknown: bool = True
    blob_auto_learn_sender: bool = True

    applicationinsights_connection_string: str = Field(
        default="",
        validation_alias=AliasChoices(
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "APPINSIGHTS_CONNECTION_STRING",
        ),
    )
    enable_application_insights: bool = Field(
        default=False,
        validation_alias="ENABLE_APPLICATION_INSIGHTS",
    )

    auth_required: bool = True
    sync_processing: bool = Field(
        default=False,
        validation_alias="SYNC_PROCESSING",
        description="Run invoice pipeline in-process (no Celery worker required)",
    )
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    default_org_slug: str = "hv-org"
    default_org_name: str = "High Volt Analytics"
    approval_policy_unlock_code: str = "000000"

    @model_validator(mode="after")
    def normalize_azure_connection_strings(self) -> Self:
        if self.postgres_host.strip() and self.postgres_user and self.postgres_password:
            self.database_url = build_postgres_url(
                host=self.postgres_host.strip(),
                port=self.postgres_port,
                db=self.postgres_db or "email_accounting",
                user=self.postgres_user,
                password=self.postgres_password,
            )
        else:
            self.database_url = normalize_database_url(self.database_url)

        if self.redis_host.strip() and self.redis_password:
            self.redis_url = build_redis_url(
                host=self.redis_host.strip(),
                port=self.redis_ssl_port,
                password=self.redis_password,
                db=0,
            )
            self.celery_broker_url = self.redis_url
            self.celery_result_backend = build_redis_url(
                host=self.redis_host.strip(),
                port=self.redis_ssl_port,
                password=self.redis_password,
                db=1,
            )
        else:
            self.redis_url = normalize_redis_url(self.redis_url)
            self.celery_broker_url = normalize_redis_url(self.celery_broker_url)
            self.celery_result_backend = normalize_redis_url(self.celery_result_backend)

        return self

    @property
    def blob_enabled(self) -> bool:
        return bool(self.azure_storage_connection_string.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if self.azure_webapp_url.strip():
            origins.append(self.azure_webapp_url.strip().rstrip("/"))
        return origins

    @property
    def graph_enabled(self) -> bool:
        return bool(
            self.azure_tenant_id
            and self.azure_client_id
            and self.azure_client_secret
            and self.graph_mailbox
        )

    @property
    def azure_di_enabled(self) -> bool:
        return bool(self.azure_di_endpoint and self.azure_di_key)

    @property
    def azure_postgres_enabled(self) -> bool:
        return "postgres.database.azure.com" in self.database_url

    @property
    def azure_redis_enabled(self) -> bool:
        return (
            "redis.cache.windows.net" in self.celery_broker_url
            or "redis.cache.windows.net" in self.redis_host
        )

    @property
    def appinsights_enabled(self) -> bool:
        return bool(self.applicationinsights_connection_string.strip())

    @property
    def application_insights_runtime_enabled(self) -> bool:
        """Send telemetry only on App Service or when explicitly enabled locally."""
        if not self.applicationinsights_connection_string.strip():
            return False
        if os.getenv("WEBSITE_SITE_NAME"):
            return True
        return self.enable_application_insights


@lru_cache
def get_settings() -> Settings:
    return Settings()
