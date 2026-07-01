"""Foreign-currency booking and payment FX variance policy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


FxRateSource = Literal["invoice_date", "payment_date", "po_date", "manual", "static_table"]


class FxPostingPolicy(BaseModel):
    """
    Per document-type FX rules.

    Booking: document currency → functional currency at booking_rate_source.
    Payment: clear AP at booked functional amount; bank at payment currency;
    difference posts to fx_gain_loss_account.
    """

    functional_currency: str = Field(default="AUD", alias="functionalCurrency")
    fx_gain_loss_account: str = Field(default="FX Gain/Loss", alias="fxGainLossAccount")
    bank_account: str = Field(default="Bank", alias="bankAccount")
    booking_rate_source: FxRateSource = Field(
        default="invoice_date",
        alias="bookingRateSource",
    )
    payment_rate_source: FxRateSource = Field(
        default="payment_date",
        alias="paymentRateSource",
    )
    require_po_invoice_currency_match: bool = Field(
        default=True,
        alias="requirePoInvoiceCurrencyMatch",
    )
    grn_currency_operational_only: bool = Field(
        default=True,
        alias="grnCurrencyOperationalOnly",
        description="GRN may differ in currency (warehouse/local); qty match only, not FX amounts.",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}


def normalize_fx_posting_policy(value: object | None) -> FxPostingPolicy | None:
    if value is None:
        return None
    if isinstance(value, FxPostingPolicy):
        return value
    if isinstance(value, dict) and value:
        try:
            return FxPostingPolicy.model_validate(value)
        except Exception:
            return None
    return None
