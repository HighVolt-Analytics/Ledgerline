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
