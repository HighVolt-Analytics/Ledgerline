from decimal import Decimal



import pytest

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.invoice import Invoice, InvoiceStatus

from app.services.invoice_data import InvoiceData, ParsedLineItem

from app.config import get_settings
from app.services.validator import (

    run_all_validations,

    vr01_total,

    vr02_unique,

    vr03_required,

    vr05_abn,

    vr06_dates,

    vr07_currency,

    vr08_gst,

)





def test_vr03_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr03_required(sample_invoice_data).passed





def test_vr03_fail() -> None:

    assert not vr03_required(InvoiceData()).passed





def test_vr03_fail_no_line_items(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.line_items = []

    assert not vr03_required(sample_invoice_data).passed





@pytest.mark.asyncio

async def test_vr05_pass(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    assert (await vr05_abn(sample_invoice_data, db_session, tenant_id=1)).passed





@pytest.mark.asyncio

async def test_vr05_fail_wrong_length(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.abn = "12345"

    assert not (await vr05_abn(sample_invoice_data, db_session, tenant_id=1)).passed





@pytest.mark.asyncio

async def test_vr05_pass_eleven_digits_without_checksum(

    db_session: AsyncSession, sample_invoice_data: InvoiceData

) -> None:

    sample_invoice_data.abn = "63110305305"

    result = await vr05_abn(sample_invoice_data, db_session, tenant_id=1)

    assert result.passed

    assert "11 digits" in result.message





@pytest.mark.asyncio

async def test_vr05_foreign_tax_id_requires_checksum_mode(

    db_session: AsyncSession, sample_invoice_data: InvoiceData, monkeypatch: pytest.MonkeyPatch

) -> None:

    monkeypatch.setenv("ABN_VALIDATION_MODE", "checksum")

    get_settings.cache_clear()

    sample_invoice_data.abn = "IE6388047V"

    assert (await vr05_abn(sample_invoice_data, db_session, tenant_id=1)).passed

    get_settings.cache_clear()





def test_vr06_fail_missing_due(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.due_date = None

    assert not vr06_dates(sample_invoice_data).passed





def test_vr06_fail_due_before_invoice(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.due_date = sample_invoice_data.invoice_date.replace(day=1)

    assert not vr06_dates(sample_invoice_data).passed





def test_vr06_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr06_dates(sample_invoice_data).passed





def test_vr07_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr07_currency(sample_invoice_data).passed





def test_vr08_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr08_gst(sample_invoice_data).passed





def test_vr08_tolerance_boundary(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.gst = Decimal("100.02")

    assert vr08_gst(sample_invoice_data).passed

    sample_invoice_data.gst = Decimal("100.03")

    assert not vr08_gst(sample_invoice_data).passed





def test_vr01_pass(sample_invoice_data: InvoiceData) -> None:

    assert vr01_total(sample_invoice_data).passed





def test_vr01_tolerance_boundary(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.total = Decimal("1100.01")

    assert vr01_total(sample_invoice_data).passed

    sample_invoice_data.total = Decimal("1100.02")

    assert not vr01_total(sample_invoice_data).passed





def test_vr07_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.currency = "USD"

    assert not vr07_currency(sample_invoice_data).passed





def test_vr08_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.gst = Decimal("1")

    assert not vr08_gst(sample_invoice_data).passed





def test_vr01_fail(sample_invoice_data: InvoiceData) -> None:

    sample_invoice_data.total = Decimal("9999")

    assert not vr01_total(sample_invoice_data).passed





@pytest.mark.asyncio

async def test_vr02_unique(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=1)).passed





@pytest.mark.asyncio

async def test_vr02_duplicate_same_vendor(

    db_session: AsyncSession,

    sample_invoice_data: InvoiceData,

    monkeypatch: pytest.MonkeyPatch,

) -> None:

    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")

    get_settings.cache_clear()

    db_session.add(

        Invoice(tenant_id=1,
            vendor="Acme Pty Ltd",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x1",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    assert not (await vr02_unique(sample_invoice_data, db_session, tenant_id=1)).passed

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

            tenant_id=1,

            vendor="Acme Pty Ltd",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x-dup-off",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    result = await vr02_unique(sample_invoice_data, db_session, tenant_id=1)

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

            tenant_id=1,

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

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=2)).passed

    get_settings.cache_clear()





@pytest.mark.asyncio

async def test_vr02_same_no_different_vendor_ok(

    db_session: AsyncSession, sample_invoice_data: InvoiceData

) -> None:

    db_session.add(

        Invoice(tenant_id=1,
            vendor="Other Co",

            invoice_no="INV-DUP",

            status=InvoiceStatus.PENDING,

            currency="AUD",

            file_hash="x2",

        )

    )

    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"

    assert (await vr02_unique(sample_invoice_data, db_session, tenant_id=1)).passed





@pytest.mark.asyncio

async def test_all_pass(db_session: AsyncSession, sample_invoice_data: InvoiceData) -> None:

    results = await run_all_validations(sample_invoice_data, db_session, tenant_id=1)

    blocking = [r for r in results if not r.skipped and r.severity == "block"]
    assert all(r.passed for r in blocking)
    assert {r.rule for r in blocking} >= {
        "VR02",
        "VR03",
        "VR05",
        "VR06",
        "VR07",
        "VR08",
        "VR01",
        "VR09",
        "VR10",
        "VR11",
    }


