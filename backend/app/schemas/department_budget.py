"""Department budget envelope schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PeriodKind = Literal["monthly", "quarterly", "annual"]


class DepartmentBudgetCreate(BaseModel):
    department: str = Field(..., min_length=1, max_length=255)
    gl_ledger: str = Field(default="", max_length=255)
    period_kind: PeriodKind
    period_key: str = Field(..., min_length=1, max_length=32)
    allocated: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None

    @field_validator("department", "gl_ledger", "period_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()


class DepartmentBudgetUpdate(BaseModel):
    department: str | None = Field(None, min_length=1, max_length=255)
    gl_ledger: str | None = Field(None, max_length=255)
    period_kind: PeriodKind | None = None
    period_key: str | None = Field(None, min_length=1, max_length=32)
    allocated: Decimal | None = Field(None, ge=0)
    notes: str | None = None

    @field_validator("department", "gl_ledger", "period_key")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class DepartmentBudgetResponse(BaseModel):
    id: int
    department: str
    gl_ledger: str = ""
    period_kind: PeriodKind
    period_key: str
    allocated: Decimal
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DepartmentBudgetUtilizationRow(BaseModel):
    department: str
    gl_ledger: str = ""
    period_kind: PeriodKind
    period_key: str
    allocated: float
    consumed: float
    remaining: float | None = None
    utilization_pct: float | None = None
    notes: str | None = None
    budget_id: int
    # Cash view — outstanding advances for employees in this department.
    # Float is reserved against dept-wide envelopes (empty GL) only so GL slices
    # are not double-charged; GL-scoped rows still show advance_float for context.
    advance_float: float = Field(
        0,
        description="Sum of outstanding Staff Advance balances for the department.",
    )
    cash_committed: float = Field(
        0,
        description="Expense consumed (+ advance float when envelope is dept-wide).",
    )
    cash_remaining: float | None = None
    cash_utilization_pct: float | None = None
