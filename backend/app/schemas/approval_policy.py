"""Approval policy schemas (org-scoped privilege matrix + routing rules)."""

from pydantic import BaseModel, Field


class PolicyRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    condition: str = Field(..., min_length=1, max_length=500)
    approver: str = Field(..., min_length=1, max_length=255)


class ApprovalPolicyPayload(BaseModel):
    locked: bool = False
    rules: list[PolicyRule] = Field(default_factory=list)
    matrix: dict[str, dict[str, bool]] = Field(default_factory=dict)


class ApprovalPolicyUnlock(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
