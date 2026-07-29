"""Org DT sales commercial invoice role — not template DT-26 fallback."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_playbook_service import (
    sales_commercial_invoice_dt_codes,
    sales_register_role_for_definition,
)
from app.services.dossier.dossier_linked_documents_service import _dt_for_sales_role
from app.services.sales.sales_document_service import resolve_sales_document_type
from app.models.invoice import Invoice
from app.tenant_ids import TESTING_TENANT_UUID


def _dt(
    code: str,
    *,
    title: str,
    route: str = "Sales Management",
    posting: str = "Yes",
    playbook: str = "",
    sales_role: str = "",
    enabled: bool = True,
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": code,
            "title": title,
            "shortTitle": title,
            "klass": "Transactional" if posting == "Yes" else "Supporting",
            "posting": posting,
            "routeTarget": route,
            "enabled": enabled,
            "playbookProfile": playbook,
            "salesBundleRole": sales_role,
        }
    )


def test_sales_register_role_from_ar_goods_org_dt() -> None:
    org_ar = _dt("DT-99", title="Customer tax invoice", playbook="ar_goods")
    assert sales_register_role_for_definition(org_ar) == "invoice"
    assert sales_commercial_invoice_dt_codes([org_ar]) == ["DT-99"]


def test_dt_for_sales_role_prefers_org_ar_goods_over_template() -> None:
    catalog = [
        _dt("DT-05", title="Sales order (copy)", posting="No", sales_role="so", playbook="supporting"),
        _dt("DT-06", title="Delivery note", posting="No", sales_role="dn", playbook="supporting"),
        _dt("DT-99", title="Harbour AR invoice", playbook="ar_goods"),
        _dt("DT-26", title="Customer tax invoice (outbound AR)", playbook="ar_goods"),
    ]
    code, label = _dt_for_sales_role("invoice", catalog)
    assert code == "DT-99"
    assert "Harbour" in label or "AR" in label
    so_code, _ = _dt_for_sales_role("so", catalog)
    assert so_code == "DT-05"
    dn_code, _ = _dt_for_sales_role("dn", catalog)
    assert dn_code == "DT-06"


def test_resolve_sales_document_type_from_org_ar_dt() -> None:
    catalog = [_dt("DT-99", title="Customer tax invoice", playbook="ar_goods")]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-99",
        route_target="Sales Management",
        currency="AUD",
    )
    assert resolve_sales_document_type(inv, document_types=catalog) == "invoice"


def test_resolve_sales_document_type_so_role_still_wins() -> None:
    catalog = [
        _dt("DT-05", title="Sales order (copy)", posting="No", sales_role="so", playbook="supporting"),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-05",
        route_target="Sales Management",
        currency="AUD",
    )
    assert resolve_sales_document_type(inv, document_types=catalog) == "so"
