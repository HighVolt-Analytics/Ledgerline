
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_field_checks import field_is_present
from app.services.classification.document_type_playbook_service import (
    _bundle_dt_satisfied,
    missing_bundle_dt_codes,
    split_bundle_items,
)
from app.services.classification.document_type_rule_engine import build_document_classifier_context
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.tenant_ids import TESTING_TENANT_UUID


def _po_type(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-02",
        title="PO copy",
        shortTitle="PO",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_po"], llm_prompt="Purchase order",
        routeTarget="Purchase Management",
        purchaseBundleRole="po",
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def _grn_type(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-03",
        title="GRN",
        shortTitle="GRN",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_grn"], llm_prompt="Goods receipt",
        routeTarget="Purchase Management",
        purchaseBundleRole="grn",
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_split_bundle_items_only_user_codes() -> None:
    definition = DocumentTypeDefinition(
        code="DT-01",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Purchase Management",
        bundleMandatory=["DT-02", "DT-03"],
    )
    mandatory, _ = split_bundle_items(definition.bundle_mandatory)
    assert mandatory == ["DT-02", "DT-03"]


@pytest.mark.asyncio
async def test_bundle_satisfied_by_purchase_role_po_upload() -> None:
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    po_present = MagicMock()
    po_present.scalar_one_or_none = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=po_present)

    satisfied = await _bundle_dt_satisfied(
        session,
        tenant_id=TESTING_TENANT_UUID,
        po_reference="PO-MKT-2026-JUN9",
        dt_code="DT-02",
        exclude_invoice_id=None,
        document_types=[_po_type()],
    )
    assert satisfied is True


@pytest.mark.asyncio
async def test_bundle_satisfied_by_purchase_role_grn_register() -> None:
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    grn_present = MagicMock()
    grn_present.scalar_one_or_none = MagicMock(return_value=99)
    session.execute = AsyncMock(return_value=grn_present)

    satisfied = await _bundle_dt_satisfied(
        session,
        tenant_id=TESTING_TENANT_UUID,
        po_reference="PO-MKT-2026-JUN9",
        dt_code="DT-03",
        exclude_invoice_id=None,
        document_types=[_grn_type()],
    )
    assert satisfied is True


@pytest.mark.asyncio
async def test_bundle_mandatory_dt04_satisfied_by_dt02_po_upload(db_session: AsyncSession) -> None:
    """Mandatory slot DT-04 is satisfied when sibling upload is classified as DT-02 with po role."""
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        po_reference="po-mkt-2026-jun9",
        document_type_code="DT-02",
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()

    mandatory_dt04 = _po_type(code="DT-04", purchaseBundleRole="")
    document_types = [_po_type(), _grn_type(), mandatory_dt04]

    missing = await missing_bundle_dt_codes(
        db_session,
        invoice=Invoice(
            id=99,
            tenant_id=TESTING_TENANT_UUID,
            po_reference="PO-MKT-2026-JUN9",
            document_type_code="DT-01",
            status=InvoiceStatus.VALIDATING,
        ),
        dt_codes=["DT-04"],
        document_types=document_types,
    )
    assert missing == []


@pytest.mark.asyncio
async def test_bundle_mandatory_infers_po_role_from_title(db_session: AsyncSession) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        po_reference="PO-9001",
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()

    mandatory = DocumentTypeDefinition(
        code="DT-04",
        title="PO (supporting)",
        shortTitle="PO (supporting)",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_po"], llm_prompt="Purchase order copy",
        routeTarget="Purchase Management",
    )
    satisfied = await _bundle_dt_satisfied(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        po_reference="po-9001",
        dt_code="DT-04",
        exclude_invoice_id=None,
        document_types=[mandatory],
    )
    assert satisfied is True


def test_total_present_from_line_items() -> None:
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING)
    parsed = InvoiceData(
        line_items=[ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=Decimal("50"))],
    )
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    assert field_is_present("subtotal", invoice=invoice, parsed=parsed, ctx=ctx)
    assert field_is_present("total", invoice=invoice, parsed=parsed, ctx=ctx)
