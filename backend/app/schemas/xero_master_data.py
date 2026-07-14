"""Xero bidirectional sync API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class XeroEntitySyncCounts(BaseModel):
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    failed: int = 0
    persisted_total: int = 0


class XeroSyncSettingsResponse(BaseModel):
    organisation: XeroEntitySyncCounts = Field(default_factory=XeroEntitySyncCounts)
    accounts: XeroEntitySyncCounts = Field(default_factory=XeroEntitySyncCounts)
    tax_rates: XeroEntitySyncCounts = Field(default_factory=XeroEntitySyncCounts)
    currencies: XeroEntitySyncCounts = Field(default_factory=XeroEntitySyncCounts)
    # Flat aliases for older clients / tests
    organisation_count: int = 0
    account: int = 0
    tax_rate: int = 0
    currency: int = 0
    committed: bool = False
    job_id: int | None = None


class XeroSyncContactsResponse(BaseModel):
    contacts: XeroEntitySyncCounts = Field(default_factory=XeroEntitySyncCounts)
    contact: int = 0
    committed: bool = False
    job_id: int | None = None


class XeroPagedMeta(BaseModel):
    total: int = 0
    limit: int = 50
    offset: int = 0


class XeroAccountItem(BaseModel):
    id: int
    xero_account_id: str
    xero_tenant_id: str
    code: str | None = None
    name: str | None = None
    account_type: str | None = None
    account_class: str | None = None
    status: str | None = None
    tax_type: str | None = None
    currency_code: str | None = None
    sync_status: str
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    source_system: str = "xero"
    source_label: str = "Source: Xero"
    external_id: str | None = None
    imported_at: datetime | None = None


class XeroAccountsResponse(XeroPagedMeta):
    items: list[XeroAccountItem]


class XeroTaxRateItem(BaseModel):
    id: int
    tax_type: str
    xero_tenant_id: str
    name: str | None = None
    status: str | None = None
    effective_rate: float | None = None
    display_tax_rate: float | None = None
    sync_status: str
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    source_system: str = "xero"
    source_label: str = "Source: Xero"
    external_id: str | None = None
    imported_at: datetime | None = None


class XeroTaxRatesResponse(XeroPagedMeta):
    items: list[XeroTaxRateItem]


class XeroContactItem(BaseModel):
    id: int
    xero_contact_id: str
    xero_tenant_id: str
    name: str | None = None
    email_address: str | None = None
    phone: str | None = None
    contact_status: str | None = None
    is_supplier: bool = False
    is_customer: bool = False
    mapping_status: str = "unmapped"
    mapped_vendor_id: int | None = None
    mapped_customer_id: int | None = None
    sync_status: str
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    source_system: str = "xero"
    source_label: str = "Source: Xero"
    external_id: str | None = None
    imported_at: datetime | None = None


class XeroContactsResponse(XeroPagedMeta):
    items: list[XeroContactItem]


class XeroSyncHistoryItem(BaseModel):
    id: int
    job_type: str
    direction: str | None = None
    entity_type: str | None = None
    status: str
    trigger_type: str | None = None
    records_fetched: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    records_failed: int = 0
    records_persisted: int = 0
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    correlation_id: str | None = None
    initiated_by: int | None = None
    created_at: datetime | None = None


class XeroSyncHistoryResponse(XeroPagedMeta):
    items: list[XeroSyncHistoryItem]


class XeroExportHistoryItem(BaseModel):
    id: int
    invoice_id: int | None = None
    external_entity_id: str | None = None
    external_number: str | None = None
    external_status: str | None = None
    sync_direction: str | None = None
    sync_status: str | None = None
    reconciliation_status: str | None = None
    last_pushed_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    last_remote_modified_at: datetime | None = None
    amount_due: float | None = None
    amount_paid: float | None = None
    is_fully_paid: bool | None = None
    sync_error_code: str | None = None
    sync_error_message: str | None = None
    source_system: str | None = None


class XeroExportHistoryResponse(XeroPagedMeta):
    items: list[XeroExportHistoryItem]


class XeroReconcileRequest(BaseModel):
    ref_id: int | None = None


class XeroReconcileResponse(BaseModel):
    job_id: int | None = None
    reconciled: int = 0
    failed: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)
    committed: bool = False


class XeroMasterTotals(BaseModel):
    accounts: int = 0
    tax_rates: int = 0
    contacts: int = 0
    currencies: int = 0
