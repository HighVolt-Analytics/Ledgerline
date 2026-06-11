"""Billing and credits schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreditPack(BaseModel):
    id: str
    name: str
    credits: int
    price_aud: int
    popular: bool = False


class BillingStateResponse(BaseModel):
    balance: int
    current_pack: str
    auto_recharge: bool
    threshold: int
    packs: list[CreditPack] = Field(default_factory=list)


class BillingSettingsUpdate(BaseModel):
    auto_recharge: bool | None = None
    threshold: int | None = None


class BillingPurchaseRequest(BaseModel):
    pack_id: str
