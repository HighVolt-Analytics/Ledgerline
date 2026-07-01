
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.account_mapper import AccountMapping
from app.services.journal_generator import generate_entries, is_balanced


def test_balanced() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 1, 15),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    lines = generate_entries(inv, AccountMapping("6100", "Software"))
    assert len(lines) == 3
    assert is_balanced(lines)


def test_ap_credit() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 1, 15),
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    ap = [ln for ln in generate_entries(inv, AccountMapping("6200", "Supplies")) if ln.account_code == "2000"]
    assert ap[0].credit == Decimal("550")
