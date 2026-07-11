"""One-shot patch: merge Xero config into config.py."""

from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "config.py"
text = p.read_text(encoding="utf-8")

old_block = """    # Xero accounting OAuth (optional)
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
    )"""

new_block = """    # Xero accounting OAuth (optional)
    xero_enabled: bool = Field(default=True, validation_alias="XERO_ENABLED")
    xero_client_id: str = Field(default="", validation_alias="XERO_CLIENT_ID")
    xero_client_secret: str = Field(default="", validation_alias="XERO_CLIENT_SECRET")
    xero_redirect_uri: str = Field(default="", validation_alias="XERO_REDIRECT_URI")
    xero_scopes: str = Field(
        default="",
        validation_alias=AliasChoices("XERO_SCOPES", "XERO_OAUTH_SCOPES"),
    )
    xero_webhook_key: str = Field(default="", validation_alias="XERO_WEBHOOK_KEY")
    xero_api_base_url: str = Field(
        default="https://api.xero.com",
        validation_alias="XERO_API_BASE_URL",
    )
    xero_identity_base_url: str = Field(
        default="https://identity.xero.com",
        validation_alias="XERO_IDENTITY_BASE_URL",
    )
    xero_token_encryption_key: str = Field(
        default="",
        validation_alias="XERO_TOKEN_ENCRYPTION_KEY",
    )
    xero_oauth_frontend_return_url: str = Field(
        default="",
        validation_alias="XERO_OAUTH_FRONTEND_RETURN_URL",
    )"""

if old_block not in text:
    raise SystemExit("Xero config block not found — already patched?")

text = text.replace(old_block, new_block)

old_prop = """    @property
    def xero_configured(self) -> bool:
        return bool(self.xero_client_id.strip() and self.xero_client_secret.strip())"""

new_prop = """    @property
    def xero_configured(self) -> bool:
        if not self.xero_enabled:
            return False
        return bool(self.xero_client_id.strip() and self.xero_client_secret.strip())

    @property
    def xero_scopes_resolved(self) -> str:
        return self.xero_scopes.strip()

    @property
    def xero_authorize_url(self) -> str:
        return "https://login.xero.com/identity/connect/authorize"

    @property
    def xero_token_url(self) -> str:
        return f"{self.xero_identity_base_url.rstrip('/')}/connect/token"

    @property
    def xero_connections_url(self) -> str:
        return f"{self.xero_api_base_url.rstrip('/')}/connections"

    def xero_accounting_api_path(self, path: str) -> str:
        base = self.xero_api_base_url.rstrip("/")
        return f"{base}/api.xro/2.0/{path.lstrip('/')}"

    @property
    def xero_token_encryption_material(self) -> str:
        explicit = self.xero_token_encryption_key.strip()
        if explicit:
            return explicit
        return self.jwt_secret"""

if old_prop not in text:
    raise SystemExit("xero_configured property block not found")

text = text.replace(old_prop, new_prop)
p.write_text(text, encoding="utf-8")
print("config.py patched")
