"""Shared helpers for Xero master-data upsert counting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def payload_hash(payload: dict[str, Any] | list[Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class EntitySyncCounters:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deactivated": self.deactivated,
            "failed": self.failed,
            "persisted_total": self.created + self.updated + self.unchanged,
        }


@dataclass
class SettingsSyncResult:
    organisation: EntitySyncCounters = field(default_factory=EntitySyncCounters)
    accounts: EntitySyncCounters = field(default_factory=EntitySyncCounters)
    tax_rates: EntitySyncCounters = field(default_factory=EntitySyncCounters)
    currencies: EntitySyncCounters = field(default_factory=EntitySyncCounters)
    committed: bool = False
    job_id: int | None = None

    def to_response(self) -> dict[str, Any]:
        accounts = self.accounts.to_dict()
        tax_rates = self.tax_rates.to_dict()
        currencies = self.currencies.to_dict()
        organisation = self.organisation.to_dict()
        return {
            "organisation": organisation,
            "accounts": accounts,
            "tax_rates": tax_rates,
            "currencies": currencies,
            "organisation_count": organisation["persisted_total"],
            "account": accounts["persisted_total"],
            "tax_rate": tax_rates["persisted_total"],
            "currency": currencies["persisted_total"],
            "committed": self.committed,
            "job_id": self.job_id,
        }


@dataclass
class ContactsSyncResult:
    contacts: EntitySyncCounters = field(default_factory=EntitySyncCounters)
    committed: bool = False
    job_id: int | None = None

    def to_response(self) -> dict[str, Any]:
        data = self.contacts.to_dict()
        return {
            "contacts": data,
            "contact": data["persisted_total"],
            "committed": self.committed,
            "job_id": self.job_id,
        }
