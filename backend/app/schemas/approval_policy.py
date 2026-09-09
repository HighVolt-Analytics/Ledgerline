"""Approval policy schemas (privilege matrix + amount-tier approval matrix)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ApprovalQuorumMode = Literal["one_way", "two_way", "three_way", "amount_tier"]


class AmountApprovalTierRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, max_length=64)
    min_amount: float = Field(ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    approval_1: str | None = None
    approval_2: str | None = None
    approval_3: str | None = None  # Payment approval


class ApprovalPolicyPayload(BaseModel):
    """Privilege matrix, per-role limits, and amount-tier approval matrix."""

    model_config = ConfigDict(extra="ignore")

    locked: bool = False
    matrix: dict[str, dict[str, bool]] = Field(default_factory=dict)
    # Placeholder per-role amount ceilings (UI); amount tiers drive runtime.
    approval_limits: dict[str, float | None] = Field(default_factory=dict)
    amount_approval_tiers: list[AmountApprovalTierRow] = Field(default_factory=list)


class ApprovalPolicyUnlock(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
