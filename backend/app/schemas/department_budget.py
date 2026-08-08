"""GL account budget envelope schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PeriodKind = Literal["monthly", "quarterly", "annual"]
BudgetEnforcement = Literal["soft", "hard"]


class DepartmentBudgetCreate(BaseModel):
    """Create a GL-account budget pot for a period."""

    gl_ledger: str = Field(..., min_length=1, max_length=255)
    period_kind: PeriodKind
    period_key: str = Field(..., min_length=1, max_length=32)
    allocated: Decimal = Field(default=Decimal("0"), ge=0)
    # Optional metadata only — not used for enforcement.
    department: str = Field(default="", max_length=255)
    enforcement: BudgetEnforcement = Field(
        default="soft",
        description="soft: over budget holds for manager; hard: block until budget raised",
    )
    notes: str | None = None

    @field_validator("department", "gl_ledger", "period_key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("enforcement", mode="before")
    @classmethod
    def _normalize_enforcement(cls, value: object) -> str:
        token = str(value or "soft").strip().lower()
        return token if token in {"soft", "hard"} else "soft"


class DepartmentBudgetUpdate(BaseModel):
    gl_ledger: str | None = Field(None, min_length=1, max_length=255)
    period_kind: PeriodKind | None = None
    period_key: str | None = Field(None, min_length=1, max_length=32)
    allocated: Decimal | None = Field(None, ge=0)
    department: str | None = Field(None, max_length=255)
    enforcement: BudgetEnforcement | None = None
    notes: str | None = None

    @field_validator("department", "gl_ledger", "period_key")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("enforcement", mode="before")
    @classmethod
    def _normalize_enforcement_optional(cls, value: object) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower()
        return token if token in {"soft", "hard"} else "soft"


class DepartmentBudgetResponse(BaseModel):
    id: int
    gl_ledger: str
    period_kind: PeriodKind
    period_key: str
    allocated: Decimal
    department: str = ""
    enforcement: BudgetEnforcement = "soft"
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlBudgetSubBreakdownRow(BaseModel):
    gl_ledger: str
    consumed: float
    pct_of_budget: float = 0


class DepartmentBudgetUtilizationRow(BaseModel):
    """Parent GL | Budget | Spent | Left for Team Expense reporting."""

    gl_ledger: str
    period_kind: PeriodKind
    period_key: str
    allocated: float
    consumed: float
    remaining: float | None = None
    utilization_pct: float | None = None
    department: str = ""
    enforcement: BudgetEnforcement = "soft"
    notes: str | None = None
    budget_id: int
    sub_breakdown: list[GlBudgetSubBreakdownRow] = Field(default_factory=list)


class GlBudgetSubAllocation(BaseModel):
    """One Sub-GL slice under a parent wallet."""

    gl_ledger: str = Field(..., min_length=1, max_length=255)
    allocated: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("gl_ledger")
    @classmethod
    def _strip_sub(cls, value: str) -> str:
        return (value or "").strip()


class ParentGlBudgetTreeUpsert(BaseModel):
    """Create/update parent GL budget and all Sub-GL budgets for one period.

    ``sum(sub_allocations.allocated)`` must equal ``allocated`` when the parent
    has COA children.
    """

    parent_gl: str = Field(..., min_length=1, max_length=255)
    period_kind: PeriodKind
    period_key: str = Field(..., min_length=1, max_length=32)
    allocated: Decimal = Field(..., ge=0)
    sub_allocations: list[GlBudgetSubAllocation] = Field(default_factory=list)
    enforcement: BudgetEnforcement = "soft"
    notes: str | None = None

    @field_validator("parent_gl", "period_key")
    @classmethod
    def _strip_tree(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("enforcement", mode="before")
    @classmethod
    def _normalize_tree_enforcement(cls, value: object) -> str:
        token = str(value or "soft").strip().lower()
        return token if token in {"soft", "hard"} else "soft"


class DepartmentBudgetImportRowErrorResponse(BaseModel):
    row_number: int
    parent_gl: str | None = None
    message: str


class DepartmentBudgetImportRowPreviewResponse(BaseModel):
    row_number: int
    parent_gl: str
    period_kind: str
    period_key: str
    action: str
    detail: str


class DepartmentBudgetImportResultResponse(BaseModel):
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[DepartmentBudgetImportRowErrorResponse] = Field(default_factory=list)
    previews: list[DepartmentBudgetImportRowPreviewResponse] = Field(default_factory=list)
