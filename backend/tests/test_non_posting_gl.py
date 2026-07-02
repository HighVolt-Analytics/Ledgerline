"""Non-posting documents must not show Suspense GL mapping."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_playbook_profile_service import (
    allows_posting_pipeline,
    clear_invoice_gl_mapping,
    gl_posting_applicable_for_invoice,
)
from app.services.non_posting_document_service import finish_non_posting_document
from app.tenant_ids import TESTING_TENANT_UUID


def _contract_definition() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-16",
            "title": "Contract / SOW",
            "shortTitle": "Contract / SOW",
            "klass": "Supporting",
            "posting": "No",
            "fraudRisk": "low",
            "oneLine": "Supporting bundle member",
            "playbook_profile": "supporting",
            "enabled": True,
            "route_target": "Purchase Management",
        }
    )


def test_allows_posting_pipeline_false_for_supporting_contract() -> None:
    definition = _contract_definition()
    assert allows_posting_pipeline(definition) is False


def test_gl_posting_not_applicable_for_po_grn_so_dn() -> None:
    po = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        purchase_document_type="po",
        route_target="Purchase Management",
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
    )
    assert gl_posting_applicable_for_invoice(po) is False

    dn = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        sales_document_type="dn",
        route_target="Sales Management",
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
    )
    assert gl_posting_applicable_for_invoice(dn) is False


def test_gl_posting_not_applicable_for_contract_document_type() -> None:
    definition = _contract_definition()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-16",
        route_target="Purchase Management",
        currency="AUD",
        status=InvoiceStatus.PENDING,
        account_code="9999",
        account_name="Suspense Account",
    )
    assert gl_posting_applicable_for_invoice(inv, document_type=definition) is False


def test_clear_invoice_gl_mapping() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        account_code="9999",
        account_name="Suspense Account",
        currency="AUD",
        status=InvoiceStatus.PENDING,
    )
    clear_invoice_gl_mapping(inv)
    assert inv.account_code is None
    assert inv.account_name is None


@pytest.mark.asyncio
async def test_finish_non_posting_document_clears_gl(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Pty Ltd",
        document_type_code="DT-16",
        route_target="Purchase Management",
        currency="AUD",
        status=InvoiceStatus.VALIDATING,
        account_code="9999",
        account_name="Suspense Account",
    )
    db_session.add(inv)
    await db_session.flush()

    await finish_non_posting_document(
        db_session,
        inv,
        definition=_contract_definition(),
    )
    await db_session.commit()

    assert inv.status == InvoiceStatus.PROCESSED
    assert inv.account_name is None
    assert inv.account_code is None
