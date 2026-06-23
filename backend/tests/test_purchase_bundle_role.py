"""Tests for user-configured purchase bundle roles on document types."""

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_playbook_service import (
    _bundle_dt_satisfied,
    split_bundle_items,
)


def _po_type(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-02",
        title="PO copy",
        shortTitle="PO",
        klass="Supporting",
        posting="No",
        fraudRisk="low",
        oneLine="Purchase order",
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
        klass="Supporting",
        posting="No",
        fraudRisk="low",
        oneLine="Goods receipt",
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
        fraudRisk="low",
        oneLine="test",
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
        tenant_id=1,
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
        tenant_id=1,
        po_reference="PO-MKT-2026-JUN9",
        dt_code="DT-03",
        exclude_invoice_id=None,
        document_types=[_grn_type()],
    )
    assert satisfied is True
