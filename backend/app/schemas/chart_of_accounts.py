"""Chart of accounts API (tenant rule book config slice)."""

from pydantic import BaseModel, Field, field_validator

from app.schemas.rule_book_config import ChartOfAccountEntry


class ChartOfAccountsResponse(BaseModel):
    accounts: list[ChartOfAccountEntry] = Field(default_factory=list)

    @classmethod
    def from_entries(cls, entries: list[ChartOfAccountEntry]) -> "ChartOfAccountsResponse":
        return cls(accounts=list(entries))


class UpdateChartOfAccountsRequest(BaseModel):
    accounts: list[ChartOfAccountEntry] = Field(default_factory=list)

    @field_validator("accounts")
    @classmethod
    def _non_empty(cls, accounts: list[ChartOfAccountEntry]) -> list[ChartOfAccountEntry]:
        if not accounts:
            raise ValueError("At least one account is required")
        return accounts

    def to_entries(self) -> list[ChartOfAccountEntry]:
        return list(self.accounts)
