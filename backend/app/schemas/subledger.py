"""Subledger balance reporting schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class SubledgerBalanceRow(BaseModel):
    registry_id: int
    slug: str
    name: str
    abn: str | None = None
    approved: bool = False
    balance: Decimal
    document_count: int = 0
    last_activity_date: date | None = None


class SubledgerUnregisteredBucket(BaseModel):
    balance: Decimal = Decimal("0")
    document_count: int = 0


class SubledgerTotals(BaseModel):
    balance: Decimal = Decimal("0")
    counterparty_count: int = 0


class SubledgerBalancesResponse(BaseModel):
    base_currency: str
    as_of: date
    control_account_code: str
    control_account_name: str
    rows: list[SubledgerBalanceRow] = Field(default_factory=list)
    unregistered: SubledgerUnregisteredBucket = Field(default_factory=SubledgerUnregisteredBucket)
    totals: SubledgerTotals = Field(default_factory=SubledgerTotals)
