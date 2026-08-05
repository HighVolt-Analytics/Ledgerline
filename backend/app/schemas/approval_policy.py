"""Approval policy schemas (org-scoped privilege matrix + routing rules)."""

from typing import Literal

from pydantic import BaseModel, Field

ApprovalQuorumMode = Literal["one_way", "two_way", "three_way"]

APPROVAL_MATRIX_MODULES: tuple[str, ...] = (
    "team_expenses",
    "expenses",
    "purchase",
    "sales",
)

_DEFAULT_BY_MODULE: dict[str, ApprovalQuorumMode] = {
    "team_expenses": "one_way",
    "expenses": "one_way",
    "purchase": "two_way",
    "sales": "one_way",
}


def _default_approval_matrix() -> "ApprovalMatrixConfig":
    return ApprovalMatrixConfig(by_module=dict(_DEFAULT_BY_MODULE))


class PolicyRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    condition: str = Field(..., min_length=1, max_length=500)
    approver: str = Field(..., min_length=1, max_length=255)


class ApprovalMatrixConfig(BaseModel):
    """Per-module quorum: how many distinct pool approvers are required."""

    by_module: dict[str, ApprovalQuorumMode] = Field(
        default_factory=lambda: dict(_DEFAULT_BY_MODULE)
    )


class ApprovalPolicyPayload(BaseModel):
    locked: bool = False
    rules: list[PolicyRule] = Field(default_factory=list)
    matrix: dict[str, dict[str, bool]] = Field(default_factory=dict)
    approval_matrix: ApprovalMatrixConfig = Field(default_factory=_default_approval_matrix)


class ApprovalPolicyUnlock(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
