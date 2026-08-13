"""DT-listed field blockers — never invent vendor/total/currency."""

from decimal import Decimal

from app.models.invoice import Invoice
from app.services.invoice.invoice_blockers import detect_invoice_blockers
from app.tenant_ids import TESTING_TENANT_UUID


def test_blockers_empty_when_dt_omits_vendor() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=None,
        total=Decimal("340000"),
        currency="MMK",
        file_hash="blk-1",
    )
    assert detect_invoice_blockers(
        inv,
        configured_keys=["total", "currency", "invoice_date", "employee_name"],
    ) == []


def test_blockers_flag_vendor_only_when_dt_lists_it() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=None,
        total=Decimal("100"),
        currency="AUD",
        file_hash="blk-2",
    )
    assert detect_invoice_blockers(inv, configured_keys=["vendor", "total"]) == ["vendor"]


def test_blockers_do_not_invent_triad_when_keys_missing() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=None,
        total=None,
        currency="",
        file_hash="blk-3",
    )
    assert detect_invoice_blockers(inv) == []
    assert detect_invoice_blockers(inv, configured_keys=[]) == []
