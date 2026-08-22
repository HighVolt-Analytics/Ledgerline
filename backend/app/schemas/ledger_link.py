"""Ledger Link export and overview schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.reconciliation import ReconciliationOverview


class LedgerExportRowResponse(BaseModel):
    id: str
    doc: str
    date: str
    party: str
    debit: str
    credit: str
    amount: float
    status: str
    currency: str = ""


class LedgerExportGroupMeta(BaseModel):
    count: int = 0
    totals_by_currency: dict[str, float] = Field(default_factory=dict)


class LedgerLinkExports(BaseModel):
    invoices: list[LedgerExportRowResponse] = Field(default_factory=list)
    bills: list[LedgerExportRowResponse] = Field(default_factory=list)
    expenses: list[LedgerExportRowResponse] = Field(default_factory=list)
    purchases: list[LedgerExportRowResponse] = Field(default_factory=list)
    payments: list[LedgerExportRowResponse] = Field(default_factory=list)
    group_meta: dict[str, LedgerExportGroupMeta] = Field(default_factory=dict)


class LedgerLinkResponse(BaseModel):
    overview: ReconciliationOverview
    exports: LedgerLinkExports
