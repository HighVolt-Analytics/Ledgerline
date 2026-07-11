"""Accounting integration OAuth schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountingConnectResponse(BaseModel):
    connect_url: str


class AccountingIntegrationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    configured: bool = False
    status: str = "disconnected"
    display_name: str | None = None
    provider_tenant_id: str | None = None
    scopes: str | None = None
    connected_at: datetime | None = None
    last_error: str | None = None


class AccountingIntegrationsStatusResponse(BaseModel):
    xero: AccountingIntegrationItem
    quickbooks_online: AccountingIntegrationItem


class AccountingDisconnectResponse(BaseModel):
    disconnected: bool
    provider: str


class XeroReadinessResponse(BaseModel):
    enabled: bool = True
    configured: bool
    connected: bool
    ready: bool
    status: str
    organisation_selection_required: bool = False
    organisation_selected: bool
    selected_xero_tenant_id: str | None = None
    selected_xero_tenant_name: str | None = None
    provider_tenant_id: str | None = None
    display_name: str | None = None
    connection_count: int = 0
    scopes: str | None = None
    token_expires_at: datetime | None = None
    needs_reauth: bool = False
    last_successful_sync_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_error: str | None = None


class XeroConnectionItem(BaseModel):
    id: int
    xero_connection_id: str
    xero_tenant_id: str
    xero_tenant_type: str | None = None
    xero_tenant_name: str | None = None
    selected: bool = False


class XeroConnectionsResponse(BaseModel):
    connections: list[XeroConnectionItem]


class XeroSelectConnectionRequest(BaseModel):
    xero_connection_id: str = Field(min_length=1)


class XeroSelectConnectionResponse(BaseModel):
    status: str
    display_name: str | None = None
    provider_tenant_id: str | None = None


class XeroSyncSettingsResponse(BaseModel):
    organisation: int = 0
    account: int = 0
    tax_rate: int = 0
    currency: int = 0


class XeroSyncContactsResponse(BaseModel):
    contact: int = 0


class XeroPushInvoiceResponse(BaseModel):
    invoice_id: int
    skipped: bool = False
    reason: str | None = None
    external_entity_id: str | None = None
    external_number: str | None = None
    external_status: str | None = None
    xero_type: str | None = None


class XeroInvoiceStatusResponse(BaseModel):
    invoice_id: int
    pushed: bool = False
    external_entity_id: str | None = None
    external_number: str | None = None
    external_status: str | None = None
    last_pushed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    payload_hash: str | None = None
