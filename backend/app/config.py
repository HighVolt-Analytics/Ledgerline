"""Load settings from environment variables."""

import os
from functools import lru_cache
from typing import Self

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    rule_book_save_debounce_ms: int = Field(
        default=2000,
        ge=0,
        validation_alias="RULE_BOOK_SAVE_DEBOUNCE_MS",
    )
    rule_book_config_path: str = Field(
        default="./app/rule_book_config.json",
        validation_alias=AliasChoices("RULE_BOOK_CONFIG_PATH", "RULE_BOOK_PATH"),
    )
    document_types_catalog_path: str = Field(
        default="./data/document_types.json",
        validation_alias="DOCUMENT_TYPES_CATALOG_PATH",
    )
    document_type_classifiers_path: str = Field(
        default="./data/document_type_classifiers.json",
        validation_alias="DOCUMENT_TYPE_CLASSIFIERS_PATH",
    )
    document_type_defaults_path: str = Field(
        default="./data/document_type_defaults.json",
        validation_alias="DOCUMENT_TYPE_DEFAULTS_PATH",
    )
    cors_origins: str = "http://localhost:5173"
    public_app_url: str = Field(
        default="",
        validation_alias="PUBLIC_APP_URL",
        description="Public LedgerLink URL for audit CSV links (e.g. http://localhost:5173 or https://staging.highvolt.tech/ledgerlink)",
    )
    public_tunnel_url: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLIC_TUNNEL_URL", "NGROK_URL"),
        description="Public HTTPS tunnel (e.g. ngrok) for invite links and OAuth callback during local testing",
    )
    root_path: str = Field(
        default="",
        validation_alias=AliasChoices("BASE_PATH", "ROOT_PATH"),
        description="Public URL path prefix when behind a reverse proxy (e.g. /ledgerlink)",
    )
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
    graph_oauth_redirect_uri: str = Field(
        default="http://localhost:8001/api/mailboxes/oauth/callback",
        validation_alias="GRAPH_OAUTH_REDIRECT_URI",
    )
    graph_oauth_frontend_return_url: str = Field(
        default="http://localhost:5173/integrations",
        validation_alias="GRAPH_OAUTH_FRONTEND_RETURN_URL",
    )
    graph_oauth_multi_tenant: bool = Field(
        default=False,
        validation_alias="GRAPH_OAUTH_MULTI_TENANT",
        description="Use login.microsoftonline.com/common for mailbox invites (requires multi-tenant Entra app)",
    )
    google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID"),
    )
    google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET"),
    )
    gmail_oauth_redirect_uri: str = Field(
        default="http://localhost:8001/api/mailboxes/gmail/oauth/callback",
        validation_alias="GMAIL_OAUTH_REDIRECT_URI",
    )
    graph_max_messages: int = 50
    graph_backfill_max_messages: int = Field(
        default=500,
        ge=1,
        le=5000,
        validation_alias="GRAPH_BACKFILL_MAX_MESSAGES",
    )
    graph_backfill_max_days: int = Field(
        default=90,
        ge=1,
        le=365,
        validation_alias="GRAPH_BACKFILL_MAX_DAYS",
    )
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
    pdf_multi_document_split: bool = Field(
        default=True,
        validation_alias="PDF_MULTI_DOCUMENT_SPLIT",
    )
    pdf_segment_max_pages: int = Field(
        default=200,
        ge=1,
        le=500,
        validation_alias="PDF_SEGMENT_MAX_PAGES",
    )
    pdf_segment_max_segments: int = Field(
        default=20,
        ge=2,
        le=50,
        validation_alias="PDF_SEGMENT_MAX_SEGMENTS",
    )
    pdf_segment_llm_enabled: bool = Field(
        default=True,
        validation_alias="PDF_SEGMENT_LLM_ENABLED",
    )
    pdf_segment_llm_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        validation_alias="PDF_SEGMENT_LLM_TIMEOUT_SECONDS",
    )
    pdf_segment_llm_prompt_version: str = Field(
        default="v1",
        validation_alias="PDF_SEGMENT_LLM_PROMPT_VERSION",
    )
    azure_di_read_model_id: str = Field(
        default="prebuilt-read",
        validation_alias="AZURE_DI_READ_MODEL_ID",
    )
    azure_di_layout_model_id: str = Field(
        default="prebuilt-layout",
        validation_alias="AZURE_DI_LAYOUT_MODEL_ID",
    )
    azure_openai_endpoint: str = Field(
        default="",
        validation_alias="AZURE_OPENAI_ENDPOINT",
    )
    azure_openai_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_KEY",
            "AZURE_OPENAI_API_KEY",
        ),
    )
    azure_openai_api_version: str = Field(
        default="2024-02-15-preview",
        validation_alias="AZURE_OPENAI_API_VERSION",
    )
    azure_openai_deployment: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_DEPLOYMENT_NAME",
        ),
    )
    azure_openai_fast_deployment: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_FAST_DEPLOYMENT",
            "AZURE_OPENAI_FAST_DEPLOYMENT_NAME",
        ),
    )
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-small",
        validation_alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    )
    sample_proposal_llm_enabled: bool = Field(
        default=False,
        validation_alias="SAMPLE_PROPOSAL_LLM_ENABLED",
    )
    sample_proposal_llm_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        validation_alias="SAMPLE_PROPOSAL_LLM_TIMEOUT_SECONDS",
    )
    runtime_llm_enabled: bool = Field(
        default=True,
        validation_alias="RUNTIME_LLM_ENABLED",
    )
    runtime_llm_timeout_seconds: int = Field(
        default=45,
        ge=5,
        le=180,
        validation_alias="RUNTIME_LLM_TIMEOUT_SECONDS",
    )
    extraction_gap_fill_enabled: bool = Field(
        default=True,
        validation_alias="EXTRACTION_GAP_FILL_ENABLED",
    )
    runtime_llm_min_confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        validation_alias="RUNTIME_LLM_MIN_CONFIDENCE",
    )
    line_gl_llm_enabled: bool = Field(
        default=True,
        validation_alias="LINE_GL_LLM_ENABLED",
    )
    google_gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GOOGLE_GEMINI_API_KEY",
            "GEMINI_API_KEY",
        ),
    )
    gemini_vision_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GEMINI_VISION_MODEL",
    )
    vision_llm_provider: str = Field(
        default="azure_di",
        validation_alias="VISION_LLM_PROVIDER",
        description="Default vision document AI: azure_di | azure_foundry | gemini_vision",
    )
    azure_ai_foundry_endpoint: str = Field(
        default="",
        validation_alias="AZURE_AI_FOUNDRY_ENDPOINT",
    )
    azure_ai_foundry_api_key: str = Field(
        default="",
        validation_alias="AZURE_AI_FOUNDRY_API_KEY",
    )
    azure_ai_foundry_deployment: str = Field(
        default="gpt-4o",
        validation_alias="AZURE_AI_FOUNDRY_DEPLOYMENT",
    )
    azure_ai_foundry_api_version: str = Field(
        default="2024-08-01-preview",
        validation_alias="AZURE_AI_FOUNDRY_API_VERSION",
    )
    policy_min_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        validation_alias="POLICY_MIN_CONFIDENCE",
    )
    ocr_min_text_chars: int = Field(
        default=80,
        ge=0,
        validation_alias="OCR_MIN_TEXT_CHARS",
    )
    llm_classification_prompt_version: str = Field(
        default="v1",
        validation_alias="LLM_CLASSIFICATION_PROMPT_VERSION",
    )
    abn_validation_mode: str = Field(default="format")
    duplicate_invoice_check_enabled: bool = Field(
        default=True,
        validation_alias="DUPLICATE_INVOICE_CHECK_ENABLED",
    )

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

    auth_required: bool = Field(default=True, validation_alias="AUTH_REQUIRED")
    sync_processing: bool = Field(
        default=False,
        validation_alias="SYNC_PROCESSING",
        description="Run invoice pipeline in-process (no Celery worker required)",
    )
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    access_token_expire_minutes: int = Field(
        default=60,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=90,
        validation_alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )
    otp_expire_minutes: int = Field(default=5, validation_alias="OTP_EXPIRE_MINUTES")
    dev_otp_code: str = Field(default="123456", validation_alias="DEV_OTP_CODE")
    super_admin_portal_embed_token: str = Field(
        default="",
        validation_alias="SUPER_ADMIN_PORTAL_EMBED_TOKEN",
        description="Secret token for super-admin portal embed links (treat like a password)",
    )
    super_admin_portal_embed_email: str = Field(
        default="",
        validation_alias="SUPER_ADMIN_PORTAL_EMBED_EMAIL",
        description="Super admin account email to sign in when embed token is valid",
    )
    super_admin_portal_embed_allowed_origins: str = Field(
        default="",
        validation_alias="SUPER_ADMIN_PORTAL_EMBED_ALLOWED_ORIGINS",
        description="Optional comma-separated origins allowed to call portal-embed login",
    )
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    environment: str = Field(
        default="",
        validation_alias="ENVIRONMENT",
        description="Deployment environment label (falls back to APP_ENV when unset)",
    )
    api_base_path: str = Field(
        default="/api",
        validation_alias="API_BASE_PATH",
        description="Public API path prefix (e.g. /api or /ledgerlink/api)",
    )
    default_tenant_slug: str = Field(default="qa-sandbox", validation_alias="DEFAULT_TENANT_SLUG")
    default_tenant_name: str = Field(default="LedgerLink QA Sandbox", validation_alias="DEFAULT_TENANT_NAME")
    approval_policy_unlock_code: str = "000000"

    # Meta / WhatsApp Cloud API
    meta_app_id: str = Field(default="", validation_alias="META_APP_ID")
    meta_app_secret: str = Field(default="", validation_alias="META_APP_SECRET")
    meta_webhook_verify_token: str = Field(
        default="",
        validation_alias="META_WEBHOOK_VERIFY_TOKEN",
    )
    whatsapp_app_id: str = Field(default="", validation_alias="WHATSAPP_APP_ID")
    whatsapp_app_secret: str = Field(default="", validation_alias="WHATSAPP_APP_SECRET")
    whatsapp_webhook_verify_token: str = Field(
        default="",
        validation_alias="WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    )
    whatsapp_graph_api_version: str = Field(
        default="v21.0",
        validation_alias="WHATSAPP_GRAPH_API_VERSION",
    )
    whatsapp_oauth_scopes: str = Field(
        default=(
            "whatsapp_business_management,"
            "whatsapp_business_messaging,"
            "business_management"
        ),
        validation_alias="WHATSAPP_OAUTH_SCOPES",
    )
    whatsapp_oauth_redirect_uri: str = Field(
        default="http://localhost:8001/auth/whatsapp/callback",
        validation_alias="WHATSAPP_OAUTH_REDIRECT_URI",
    )
    whatsapp_oauth_frontend_return_url: str = Field(
        default="",
        validation_alias="WHATSAPP_OAUTH_FRONTEND_RETURN_URL",
    )

    # Xero accounting OAuth (optional)
    xero_client_id: str = Field(default="", validation_alias="XERO_CLIENT_ID")
    xero_client_secret: str = Field(default="", validation_alias="XERO_CLIENT_SECRET")
    xero_redirect_uri: str = Field(default="", validation_alias="XERO_REDIRECT_URI")
    xero_oauth_scopes: str = Field(
        default="openid profile email accounting.settings.read offline_access",
        validation_alias="XERO_OAUTH_SCOPES",
    )
    xero_oauth_frontend_return_url: str = Field(
        default="",
        validation_alias="XERO_OAUTH_FRONTEND_RETURN_URL",
    )

    # QuickBooks Online accounting OAuth (optional)
    quickbooks_client_id: str = Field(default="", validation_alias="QUICKBOOKS_CLIENT_ID")
    quickbooks_client_secret: str = Field(
        default="",
        validation_alias="QUICKBOOKS_CLIENT_SECRET",
    )
    quickbooks_redirect_uri: str = Field(default="", validation_alias="QUICKBOOKS_REDIRECT_URI")
    quickbooks_environment: str = Field(
        default="sandbox",
        validation_alias="QUICKBOOKS_ENVIRONMENT",
    )
    quickbooks_oauth_scopes: str = Field(
        default="com.intuit.quickbooks.accounting",
        validation_alias="QUICKBOOKS_OAUTH_SCOPES",
    )
    quickbooks_oauth_frontend_return_url: str = Field(
        default="",
        validation_alias="QUICKBOOKS_OAUTH_FRONTEND_RETURN_URL",
    )
    accounting_oauth_frontend_return_url: str = Field(
        default="",
        validation_alias="ACCOUNTING_OAUTH_FRONTEND_RETURN_URL",
    )

    # Stripe Connect / payments (optional — empty until configured)
    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    stripe_connect_client_id: str = Field(
        default="",
        validation_alias="STRIPE_CONNECT_CLIENT_ID",
    )
    stripe_mode: str = Field(default="sandbox", validation_alias="STRIPE_MODE")
    stripe_return_url: str = Field(default="", validation_alias="STRIPE_RETURN_URL")
    stripe_refresh_url: str = Field(default="", validation_alias="STRIPE_REFRESH_URL")
    stripe_oauth_redirect_url: str = Field(
        default="",
        validation_alias="STRIPE_OAUTH_REDIRECT_URL",
        description="Stripe Connect OAuth redirect URI (must match Stripe Dashboard Connect/OAuth settings)",
    )
    stripe_payments_execution_enabled: bool = Field(
        default=False,
        validation_alias="STRIPE_PAYMENTS_EXECUTION_ENABLED",
    )
    stripe_live_payments_enabled: bool = Field(
        default=False,
        validation_alias="STRIPE_LIVE_PAYMENTS_ENABLED",
    )
    payment_manual_execution_enabled: bool = Field(
        default=False,
        validation_alias="PAYMENT_MANUAL_EXECUTION_ENABLED",
    )
    payment_manual_execution_limit_usd: float = Field(
        default=1000.0,
        ge=0,
        validation_alias=AliasChoices(
            "PAYMENT_MANUAL_EXECUTION_LIMIT_USD",
            "PAYMENT_MANUAL_EXECUTION_LIMIT_AUD",
        ),
    )
    payment_execution_disabled: bool = Field(
        default=False,
        validation_alias="PAYMENT_EXECUTION_DISABLED",
        description="Emergency kill switch for all payment execution orchestration endpoints",
    )

    payment_environment_label: str = Field(
        default="",
        validation_alias="PAYMENT_ENVIRONMENT_LABEL",
    )
    public_app_base_url: str = Field(
        default="",
        validation_alias="PUBLIC_APP_BASE_URL",
        description="Public LedgerLink app URL (e.g. https://ledgerlink.highvolt.tech)",
    )
    public_api_base_url: str = Field(
        default="",
        validation_alias="PUBLIC_API_BASE_URL",
        description="Public LedgerLink API base URL (e.g. https://ledgerlink.highvolt.tech/api)",
    )

    # Stripe Global Payouts (configuration only — no outbound API calls until approved)
    stripe_global_payouts_enabled: bool = Field(
        default=False,
        validation_alias="STRIPE_GLOBAL_PAYOUTS_ENABLED",
    )
    stripe_global_payouts_access_status: str = Field(
        default="not_requested",
        validation_alias="STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS",
    )
    stripe_global_payouts_financial_account_id: str = Field(
        default="",
        validation_alias="STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID",
    )
    stripe_global_payouts_webhook_secret: str = Field(
        default="",
        validation_alias="STRIPE_GLOBAL_PAYOUTS_WEBHOOK_SECRET",
    )
    stripe_global_payouts_max_amount_usd: float = Field(
        default=1000.0,
        ge=0,
        validation_alias="STRIPE_GLOBAL_PAYOUTS_MAX_AMOUNT_USD",
    )
    stripe_global_payouts_supported_countries: str = Field(
        default="AU",
        validation_alias="STRIPE_GLOBAL_PAYOUTS_SUPPORTED_COUNTRIES",
    )
    stripe_global_payouts_supported_currencies: str = Field(
        default="AUD,USD",
        validation_alias="STRIPE_GLOBAL_PAYOUTS_SUPPORTED_CURRENCIES",
    )

    # Viber Public Account Bot API
    viber_auth_token: str = Field(default="", validation_alias="VIBER_AUTH_TOKEN")
    viber_webhook_url: str = Field(default="", validation_alias="VIBER_WEBHOOK_URL")

    @field_validator("root_path", mode="before")
    @classmethod
    def normalize_root_path(cls, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if not text.startswith("/"):
            text = f"/{text}"
        return text.rstrip("/")

    @field_validator("api_base_path", mode="before")
    @classmethod
    def normalize_api_base_path(cls, value: object) -> str:
        if value is None:
            return "/api"
        text = str(value).strip() or "/api"
        if not text.startswith("/"):
            text = f"/{text}"
        return text.rstrip("/") or "/api"

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def resolve_environment_default(self) -> Self:
        if not self.environment.strip():
            self.environment = self.app_env.strip()
        return self

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

    @model_validator(mode="after")
    def apply_public_tunnel(self) -> Self:
        """When ngrok (or similar) is set, use it for invite links and OAuth callback."""
        tunnel = self.public_tunnel_url.strip().rstrip("/")
        if not tunnel:
            return self

        self.public_app_url = tunnel

        redirect = self.graph_oauth_redirect_uri.strip()
        if not redirect or "localhost" in redirect or "127.0.0.1" in redirect:
            self.graph_oauth_redirect_uri = f"{tunnel}/api/mailboxes/oauth/callback"

        gmail_redirect = self.gmail_oauth_redirect_uri.strip()
        if not gmail_redirect or "localhost" in gmail_redirect or "127.0.0.1" in gmail_redirect:
            self.gmail_oauth_redirect_uri = f"{tunnel}/api/mailboxes/gmail/oauth/callback"

        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if tunnel not in origins:
            origins.append(tunnel)
        self.cors_origins = ",".join(origins)

        wa_redirect = self.whatsapp_oauth_redirect_uri.strip()
        if not wa_redirect or "localhost" in wa_redirect or "127.0.0.1" in wa_redirect:
            self.whatsapp_oauth_redirect_uri = f"{tunnel}/auth/whatsapp/callback"

        return self

    @model_validator(mode="after")
    def apply_azure_webapp_public_url(self) -> Self:
        """Use AZURE_WEBAPP_URL for invite/OAuth links when env still has localhost defaults."""
        webapp = self.azure_webapp_url.strip().rstrip("/")
        if not webapp:
            return self

        public = self.public_app_url.strip().rstrip("/")
        if not public or "localhost" in public or "127.0.0.1" in public:
            self.public_app_url = webapp

        frontend = self.graph_oauth_frontend_return_url.strip()
        if not frontend or "localhost" in frontend or "127.0.0.1" in frontend:
            self.graph_oauth_frontend_return_url = f"{webapp}/integrations"

        redirect = self.graph_oauth_redirect_uri.strip()
        if not redirect or "localhost" in redirect or "127.0.0.1" in redirect:
            self.graph_oauth_redirect_uri = f"{webapp}/api/mailboxes/oauth/callback"

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
    def graph_credentials_configured(self) -> bool:
        return bool(
            self.azure_tenant_id.strip()
            and self.azure_client_id.strip()
            and self.azure_client_secret.strip()
        )

    @property
    def graph_enabled(self) -> bool:
        """Graph API usable when Azure app credentials are set (app-only and/or OAuth)."""
        if not self.graph_credentials_configured:
            return False
        return bool(self.graph_mailbox.strip() or self.graph_oauth_redirect_uri.strip())

    @property
    def azure_di_enabled(self) -> bool:
        return bool(self.azure_di_endpoint and self.azure_di_key)

    @property
    def azure_openai_configured(self) -> bool:
        return bool(self.azure_openai_endpoint.strip() and self.azure_openai_key.strip())

    @property
    def azure_openai_chat_deployment(self) -> str:
        fast = self.azure_openai_fast_deployment.strip()
        if fast:
            return fast
        return self.azure_openai_deployment.strip() or "gpt-4o-mini"

    @property
    def azure_openai_enabled(self) -> bool:
        return bool(self.sample_proposal_llm_enabled and self.azure_openai_configured)

    @property
    def runtime_llm_available(self) -> bool:
        return bool(self.runtime_llm_enabled and self.azure_openai_configured)

    @property
    def line_gl_llm_available(self) -> bool:
        return bool(
            self.line_gl_llm_enabled
            and self.runtime_llm_available
        )

    @property
    def gemini_configured(self) -> bool:
        return bool(self.google_gemini_api_key.strip())

    @property
    def gemini_vision_available(self) -> bool:
        return self.gemini_configured

    @property
    def azure_foundry_vision_configured(self) -> bool:
        return bool(
            self.azure_ai_foundry_endpoint.strip()
            and self.azure_ai_foundry_api_key.strip()
            and self.azure_ai_foundry_deployment.strip()
        )

    @property
    def azure_foundry_vision_available(self) -> bool:
        return self.azure_foundry_vision_configured

    @property
    def default_document_ai_provider(self) -> str:
        token = self.vision_llm_provider.strip().lower()
        if token in {"azure_foundry", "azure_foundry_vision"}:
            return "azure_foundry_vision"
        if token in {"gemini", "gemini_vision"}:
            return "gemini_vision"
        return "azure_di"

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
    def whatsapp_effective_app_id(self) -> str:
        return (self.whatsapp_app_id or self.meta_app_id).strip()

    @property
    def whatsapp_effective_app_secret(self) -> str:
        return (self.whatsapp_app_secret or self.meta_app_secret).strip()

    @property
    def whatsapp_effective_verify_token(self) -> str:
        return (
            self.whatsapp_webhook_verify_token or self.meta_webhook_verify_token
        ).strip()

    @property
    def whatsapp_configured(self) -> bool:
        return bool(
            self.whatsapp_effective_app_id
            and self.whatsapp_effective_app_secret
            and self.whatsapp_effective_verify_token
        )

    @property
    def viber_effective_auth_token(self) -> str:
        return self.viber_auth_token.strip()

    @property
    def viber_configured(self) -> bool:
        return bool(self.viber_effective_auth_token)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    @property
    def is_preview(self) -> bool:
        return self.app_env.strip().lower() == "preview"

    @property
    def smtp_explicitly_configured(self) -> bool:
        """True when SMTP_HOST points to a real relay (not dev localhost defaults)."""
        host = self.smtp_host.strip().lower()
        return host not in ("", "localhost", "127.0.0.1")

    @property
    def smtp_allowed_for_outbound(self) -> bool:
        """Production must not use implicit localhost:1025; dev/preview may."""
        if self.is_production:
            return self.smtp_explicitly_configured
        return True

    @property
    def payment_environment_label_resolved(self) -> str:
        explicit = self.payment_environment_label.strip()
        if explicit:
            return explicit
        if self.is_production:
            return "Production"
        if self.is_preview:
            return "Preview"
        return "Development"

    @property
    def public_app_base_url_resolved(self) -> str:
        explicit = self.public_app_base_url.strip() or self.public_app_url.strip()
        if explicit:
            return explicit.rstrip("/")
        webapp = self.azure_webapp_url.strip().rstrip("/")
        return webapp

    @property
    def public_api_base_url_resolved(self) -> str:
        explicit = self.public_api_base_url.strip()
        if explicit:
            return explicit.rstrip("/")
        base = self.public_app_base_url_resolved
        return f"{base}/api" if base else ""

    @property
    def whatsapp_frontend_return_url(self) -> str:
        explicit = self.whatsapp_oauth_frontend_return_url.strip()
        if explicit:
            return explicit.rstrip("/")
        return self.graph_oauth_frontend_return_url.rstrip("/")

    @property
    def xero_configured(self) -> bool:
        return bool(self.xero_client_id.strip() and self.xero_client_secret.strip())

    @property
    def quickbooks_configured(self) -> bool:
        return bool(
            self.quickbooks_client_id.strip() and self.quickbooks_client_secret.strip()
        )

    @property
    def quickbooks_sandbox_mode(self) -> bool:
        return self.quickbooks_environment.strip().lower() in ("sandbox", "test")

    @property
    def accounting_oauth_frontend_return_url_resolved(self) -> str:
        explicit = self.accounting_oauth_frontend_return_url.strip()
        if explicit:
            return explicit.rstrip("/")
        xero_explicit = self.xero_oauth_frontend_return_url.strip()
        if xero_explicit:
            return xero_explicit.rstrip("/")
        qbo_explicit = self.quickbooks_oauth_frontend_return_url.strip()
        if qbo_explicit:
            return qbo_explicit.rstrip("/")
        return self.graph_oauth_frontend_return_url.rstrip("/")

    @property
    def stripe_sandbox_mode(self) -> bool:
        return self.stripe_mode.strip().lower() in ("sandbox", "test")

    @property
    def stripe_mode_normalized(self) -> str:
        mode = self.stripe_mode.strip().lower()
        if mode in ("live", "production"):
            return "live"
        return "test"

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key.strip())

    @property
    def stripe_connect_configured(self) -> bool:
        return bool(
            self.stripe_secret_key.strip() and self.stripe_connect_client_id.strip()
        )

    @property
    def stripe_webhooks_configured(self) -> bool:
        return bool(
            self.stripe_secret_key.strip() and self.stripe_webhook_secret.strip()
        )

    @property
    def stripe_payment_execution_enabled(self) -> bool:
        return bool(self.stripe_payments_execution_enabled)

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
