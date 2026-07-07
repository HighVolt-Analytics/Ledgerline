
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from decimal import Decimal



import pytest

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.invoice import Invoice, InvoiceStatus

from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

from app.config import get_settings
from app.services.rule_book.validator import (

    run_all_validations,

    vr01_total,

    vr02_unique,

    vr03_compulsory_fields,

    vr03_required,

    vr05_abn,

    vr07_currency,

    vr08_gst,

)





def test_vr03_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr03_required(sample_invoice_data).passed


def test_vr03_compulsory_fields_subset() -> None:
    from app.tenant_ids import TESTING_TENANT_UUID

    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="Acme", total=Decimal("100"))
    parsed = InvoiceData(
        vendor="Acme",
        total=Decimal("100"),
        line_items=[ParsedLineItem(description="Item", amount=Decimal("100"))],
    )
    assert vr03_compulsory_fields(invoice, parsed, ["vendor", "total"]).passed
    assert not vr03_compulsory_fields(invoice, parsed, ["vendor", "invoice_no"]).passed


def test_vr03_compulsory_fields_empty_is_skipped() -> None:
    from app.tenant_ids import TESTING_TENANT_UUID

    invoice = Invoice(tenant_id=TESTING_TENANT_UUID)
    parsed = InvoiceData()
    result = vr03_compulsory_fields(invoice, parsed, [])
    assert result.passed
    assert result.skipped


def test_vr03_fail() -> None:

    assert not vr03_required(InvoiceData()).passed





def test_vr03_fail_no_line_items(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.line_items = []

    assert not vr03_required(sample_invoice_data).passed





@pytest.mark.asyncio

async def test_vr05_pass(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    assert (await vr05_abn(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed





@pytest.mark.asyncio

async def test_vr05_fail_wrong_length(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.abn = "12345"

    assert not (await vr05_abn(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed





@pytest.mark.asyncio

async def test_vr05_pass_eleven_digits_without_checksum(

    db_session: AsyncSession, sample_invoice_data: InvoiceData

) -> None:

    sample_invoice_data.abn = "63110305305"

    result = await vr05_abn(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)

    assert result.passed

    assert "11 digits" in result.message





@pytest.mark.asyncio

async def test_vr05_foreign_tax_id_requires_checksum_mode(

    db_session: AsyncSession, sample_invoice_data: InvoiceData, monkeypatch: pytest.MonkeyPatch

) -> None:

    monkeypatch.setenv("ABN_VALIDATION_MODE", "checksum")

    get_settings.cache_clear()

    sample_invoice_data.abn = "IE6388047V"

    assert (await vr05_abn(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed

    get_settings.cache_clear()





def test_vr07_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr07_currency(sample_invoice_data, expected_currency="AUD").passed





def test_vr08_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr08_gst(sample_invoice_data, expected_currency="AUD").passed





def test_vr08_tolerance_boundary(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.gst = Decimal("100.02")

    assert vr08_gst(sample_invoice_data, expected_currency="AUD").passed

    sample_invoice_data.gst = Decimal("100.03")

    assert not vr08_gst(sample_invoice_data, expected_currency="AUD").passed





def test_vr07_pass_sgd(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.currency = "SGD"
    assert vr07_currency(sample_invoice_data, expected_currency="SGD").passed


def test_vr07_fail_usd_for_sgd_org(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.currency = "USD"
    assert not vr07_currency(sample_invoice_data, expected_currency="SGD").passed


def test_vr08_skips_gst_for_foreign_currency(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.currency = "USD"
    sample_invoice_data.gst = None
    sample_invoice_data.subtotal = Decimal("1000.00")

    result = vr08_gst(sample_invoice_data, expected_currency="AUD")

    assert result.passed
    assert "foreign invoice" in result.message.lower()


def test_vr08_validates_gst_for_org_currency(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.currency = "USD"
    assert vr08_gst(sample_invoice_data, expected_currency="USD").passed


def test_vr01_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr01_total(sample_invoice_data).passed





def test_vr01_tolerance_boundary(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.total = Decimal("1100.01")

    assert vr01_total(sample_invoice_data).passed

    sample_invoice_data.total = Decimal("1100.02")

    assert not vr01_total(sample_invoice_data).passed





def test_vr07_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.currency = "USD"

    assert not vr07_currency(sample_invoice_data, expected_currency="AUD").passed





def test_vr08_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.gst = Decimal("1")

    assert not vr08_gst(sample_invoice_data, expected_currency="AUD").passed




def test_vr08_pass_at_fifteen_percent(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.gst_rate = Decimal("15")
    sample_invoice_data.subtotal = Decimal("1000.00")
    sample_invoice_data.gst = Decimal("150.00")
    sample_invoice_data.total = Decimal("1150.00")

    assert vr08_gst(sample_invoice_data, expected_currency="AUD").passed




def test_vr08_skips_when_rate_unknown(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.gst_rate = None
    sample_invoice_data.subtotal = Decimal("0")
    sample_invoice_data.gst = Decimal("0")

    result = vr08_gst(sample_invoice_data, expected_currency="AUD")

    assert result.skipped
    assert "GST rate could not be determined" in result.message





def test_vr01_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.total = Decimal("9999")

    assert not vr01_total(sample_invoice_data).passed




def test_vr08_skips_when_totals_missing(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.subtotal = None
    sample_invoice_data.gst = None

    result = vr08_gst(sample_invoice_data, expected_currency="AUD")

    assert result.skipped
    assert result.passed
    assert result.rule == "VR08"




def test_vr01_skips_when_totals_missing(sample_invoice_data: InvoiceData) -> None:
    sample_invoice_data.subtotal = None
    sample_invoice_data.gst = None
    sample_invoice_data.total = None

    result = vr01_total(sample_invoice_data)

    assert result.skipped
    assert result.passed
    assert result.rule == "VR01"





@pytest.mark.asyncio

async def test_vr02_unique(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed





@pytest.mark.asyncio

async def test_vr02_duplicate_same_vendor(

    db_session: AsyncSession,

    sample_invoice_data: InvoiceData,

    monkeypatch: pytest.MonkeyPatch,

) -> None:

    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")

    get_settings.cache_clear()

    db_session.add(

        Invoice(tenant_id=TESTING_TENANT_UUID,
            vendor="Acme Pty Ltd",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x1",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    assert not (await vr02_unique(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed

    get_settings.cache_clear()





@pytest.mark.asyncio

async def test_vr02_disabled_allows_duplicate(

    db_session: AsyncSession,
    sample_invoice_data: InvoiceData,
    monkeypatch: pytest.MonkeyPatch,

) -> None:

    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "false")
    get_settings.cache_clear()

    db_session.add(

        Invoice(

            tenant_id=TESTING_TENANT_UUID,

            vendor="Acme Pty Ltd",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x-dup-off",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    result = await vr02_unique(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)

    assert result.passed

    assert "disabled" in result.message.lower()

    get_settings.cache_clear()





@pytest.mark.asyncio

async def test_vr02_same_no_different_org_ok(

    db_session: AsyncSession,

    sample_invoice_data: InvoiceData,

    monkeypatch: pytest.MonkeyPatch,

) -> None:

    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")

    get_settings.cache_clear()

    db_session.add(

        Invoice(

            tenant_id=TESTING_TENANT_UUID,

            vendor="Atlassian Pty Ltd",

            invoice_no="ATL-2026-55721",

            status=InvoiceStatus.DUPLICATE_SKIPPED,

            currency="AUD",

            file_hash="org1-atl",

        )

    )

    await db_session.flush()

    sample_invoice_data.vendor = "Atlassian Pty Ltd"

    sample_invoice_data.invoice_no = "ATL-2026-55721"

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=PLATFORM_TENANT_UUID)).passed

    get_settings.cache_clear()





@pytest.mark.asyncio

async def test_vr02_same_no_different_vendor_ok(

    db_session: AsyncSession, sample_invoice_data: InvoiceData

) -> None:

    db_session.add(

        Invoice(tenant_id=TESTING_TENANT_UUID,
            vendor="Other Co",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x2",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)).passed





@pytest.mark.asyncio

async def test_all_pass(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    results = await run_all_validations(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)

    blocking = [r for r in results if not r.skipped and r.severity == "block"]
    failed = [r for r in blocking if not r.passed]
    assert not failed, [(r.rule, r.message) for r in failed]
    assert {r.rule for r in blocking} >= {
        "VR02",
        "VR03",
        "VR05",
        "VR07",
        "VR08",
        "VR01",
        "VR09",
        "VR10",
        "VR11",
    }


