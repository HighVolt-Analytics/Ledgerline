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


class LedgerLinkExports(BaseModel):
    invoices: list[LedgerExportRowResponse] = Field(default_factory=list)
    bills: list[LedgerExportRowResponse] = Field(default_factory=list)
    expenses: list[LedgerExportRowResponse] = Field(default_factory=list)
    purchases: list[LedgerExportRowResponse] = Field(default_factory=list)
    payments: list[LedgerExportRowResponse] = Field(default_factory=list)


class LedgerLinkResponse(BaseModel):
    overview: ReconciliationOverview
    exports: LedgerLinkExports
