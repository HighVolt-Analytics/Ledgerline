"""Chart of accounts API (tenant rule book config slice)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.rule_book_config import ChartOfAccountEntry, ChartOfAccountType, SubLedgerEntry
from app.schemas.tax_rates import BillProcessingTaxProvider


class PlatformChartOfAccount(BaseModel):
    xero_account_id: str
    code: str
    name: str
    type: ChartOfAccountType
    sub_type: str
    can_edit: bool = True
    can_delete: bool = True
    can_pull: bool = True
    linked_providers: list[str] = Field(default_factory=list)
    sub_ledgers: list[SubLedgerEntry] = Field(default_factory=list)
    status: str | None = None


class ChartOfAccountsResponse(BaseModel):
    accounts: list[ChartOfAccountEntry] = Field(default_factory=list)
    local_accounts: list[ChartOfAccountEntry] = Field(default_factory=list)
    platform_accounts: list[PlatformChartOfAccount] = Field(default_factory=list)
    xero_connected: bool = False
    source: Literal["none", "xero"] = "none"
    provider: BillProcessingTaxProvider | None = None

    @classmethod
    def from_entries(cls, entries: list[ChartOfAccountEntry]) -> "ChartOfAccountsResponse":
        return cls(
            accounts=list(entries),
            local_accounts=list(entries),
            platform_accounts=[],
            xero_connected=False,
            source="none",
            provider=None,
        )


class UpdateChartOfAccountsRequest(BaseModel):
    accounts: list[ChartOfAccountEntry] = Field(default_factory=list)

    @field_validator("accounts")
    @classmethod
    def _valid_rows(cls, accounts: list[ChartOfAccountEntry]) -> list[ChartOfAccountEntry]:
        return accounts

    def to_entries(self) -> list[ChartOfAccountEntry]:
        return list(self.accounts)


class UpsertXeroChartOfAccountRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=10)
    name: str = Field(..., min_length=1, max_length=150)
    type: ChartOfAccountType
    sub_type: str = Field(..., min_length=1, max_length=32)
    sub_ledgers: list[SubLedgerEntry] = Field(default_factory=list)
