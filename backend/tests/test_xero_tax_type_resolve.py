from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.integrations.xero.tax_rates import (
    INVOICE_XERO_TAX_TYPE_CHARGED,
    INVOICE_XERO_TAX_TYPE_ZERO,
    match_xero_tax_type_for_percent,
    resolve_invoice_xero_tax_type,
)
from app.models.xero_tax_rate import XeroTaxRate
from app.tenant_ids import TESTING_TENANT_UUID


def _row(*, tax_type: str, name: str, rate: str | None) -> XeroTaxRate:
    return XeroTaxRate(
        tenant_id=TESTING_TENANT_UUID,
        accounting_integration_id=1,
        xero_tenant_id="xero-org-1",
        tax_type=tax_type,
        name=name,
        effective_rate=Decimal(rate) if rate is not None else None,
        sync_status="active",
    )


def test_first_percent_match_wins() -> None:
    rows = [
        _row(tax_type="OUTPUT", name="GST on Income", rate="10"),
        _row(tax_type="INPUT", name="GST on Expenses", rate="10"),
    ]
    assert match_xero_tax_type_for_percent(rows, Decimal("10")) == "OUTPUT"
    ordered = sorted(rows, key=lambda r: (r.name or "", r.tax_type))
    assert match_xero_tax_type_for_percent(ordered, Decimal("10.00")) == "INPUT"


def test_custom_tax_type_is_used_when_rate_matches() -> None:
    rows = [_row(tax_type="TAX001", name="CLC 10", rate="10")]
    assert match_xero_tax_type_for_percent(rows, Decimal("10")) == "TAX001"


def test_no_percent_match_returns_none() -> None:
    rows = [_row(tax_type="INPUT", name="GST on Expenses", rate="10")]
    assert match_xero_tax_type_for_percent(rows, Decimal("15")) is None


@pytest.mark.asyncio
async def test_resolve_sends_input_when_tax_is_charged(db_session) -> None:
    invoice = SimpleNamespace(gst=Decimal("12"), gst_rate=Decimal("15"))
    result = await resolve_invoice_xero_tax_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        invoice=invoice,
    )
    assert result == INVOICE_XERO_TAX_TYPE_CHARGED


@pytest.mark.asyncio
async def test_resolve_sends_exemptinput_when_gst_is_zero(db_session) -> None:
    invoice = SimpleNamespace(gst=Decimal("0"), gst_rate=Decimal("10"))
    result = await resolve_invoice_xero_tax_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        invoice=invoice,
    )
    assert result == INVOICE_XERO_TAX_TYPE_ZERO


@pytest.mark.asyncio
async def test_resolve_sends_input_from_nonzero_rate_when_gst_missing(db_session) -> None:
    invoice = SimpleNamespace(gst=None, gst_rate=Decimal("10"))
    result = await resolve_invoice_xero_tax_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        invoice=invoice,
    )
    assert result == INVOICE_XERO_TAX_TYPE_CHARGED


@pytest.mark.asyncio
async def test_resolve_sends_exemptinput_from_zero_rate_when_gst_missing(db_session) -> None:
    invoice = SimpleNamespace(gst=None, gst_rate=Decimal("0"))
    result = await resolve_invoice_xero_tax_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        invoice=invoice,
    )
    assert result == INVOICE_XERO_TAX_TYPE_ZERO


@pytest.mark.asyncio
async def test_resolve_omits_tax_when_gst_and_rate_missing(db_session) -> None:
    invoice = SimpleNamespace(gst=None, gst_rate=None)
    result = await resolve_invoice_xero_tax_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        invoice=invoice,
    )
    assert result is None
