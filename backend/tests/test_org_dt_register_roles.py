"""Org DT purchase/sales commercial register roles — catalogue-first, not template codes."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_register_roles import (
    dt_code_for_register_role,
    purchase_commercial_invoice_dt_codes,
    purchase_register_role_for_definition,
    sales_commercial_invoice_dt_codes,
    sales_register_role_for_definition,
)
from app.services.dossier.dossier_linked_documents_service import (
    _dt_for_purchase_role,
    _dt_for_sales_role,
)
from app.services.purchase.purchase_document_service import resolve_purchase_document_type
from app.services.sales.sales_document_service import resolve_sales_document_type
from app.tenant_ids import TESTING_TENANT_UUID


def _dt(
    code: str,
    *,
    title: str,
    route: str = "Purchase Management",
    posting: str = "Yes",
    playbook: str = "",
    purchase_role: str = "",
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
            "purchaseBundleRole": purchase_role,
            "salesBundleRole": sales_role,
        }
    )


def test_purchase_register_role_from_po_goods_org_dt() -> None:
    org = _dt("DT-88", title="Harbour commercial invoice", playbook="po_goods")
    assert purchase_register_role_for_definition(org) == "invoice"
    assert purchase_commercial_invoice_dt_codes([org]) == ["DT-88"]


def test_dt_for_purchase_role_prefers_org_po_goods_over_template() -> None:
    catalog = [
        _dt("DT-05", title="Purchase order (copy)", posting="No", purchase_role="po", playbook="supporting"),
        _dt("DT-06", title="Goods receipt", posting="No", purchase_role="grn", playbook="supporting"),
        _dt("DT-88", title="Harbour AP invoice", playbook="po_goods"),
        _dt("DT-01", title="Commercial invoice", playbook="po_goods"),
    ]
    code, label = _dt_for_purchase_role("invoice", catalog)
    assert code == "DT-88"
    assert "Harbour" in label or "AP" in label
    assert _dt_for_purchase_role("po", catalog)[0] == "DT-05"
    assert _dt_for_purchase_role("grn", catalog)[0] == "DT-06"


def test_resolve_purchase_document_type_from_org_po_dt() -> None:
    catalog = [_dt("DT-88", title="Harbour commercial invoice", playbook="po_goods")]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-88",
        route_target="Purchase Management",
        currency="AUD",
    )
    assert resolve_purchase_document_type(inv, document_types=catalog) == "invoice"


def test_resolve_purchase_document_type_po_role_still_wins() -> None:
    catalog = [
        _dt("DT-05", title="Purchase order (copy)", posting="No", purchase_role="po", playbook="supporting"),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-05",
        route_target="Purchase Management",
        currency="AUD",
    )
    assert resolve_purchase_document_type(inv, document_types=catalog) == "po"


def test_sales_register_role_still_org_first() -> None:
    org_ar = _dt(
        "DT-99",
        title="Customer tax invoice",
        route="Sales Management",
        playbook="ar_goods",
    )
    assert sales_register_role_for_definition(org_ar) == "invoice"
    assert sales_commercial_invoice_dt_codes([org_ar]) == ["DT-99"]
    code, _ = _dt_for_sales_role("invoice", [org_ar])
    assert code == "DT-99"


def test_dt_code_for_register_role_shared_fallbacks() -> None:
    empty_code, empty_label = dt_code_for_register_role(
        side="purchase", role="po", document_types=[]
    )
    assert empty_code == "DT-02"
    assert "Purchase" in empty_label

    sales_code, _ = dt_code_for_register_role(side="sales", role="invoice", document_types=[])
    assert sales_code == "DT-26"


def test_resolve_sales_document_type_from_org_ar_dt() -> None:
    catalog = [
        _dt("DT-99", title="Customer tax invoice", route="Sales Management", playbook="ar_goods")
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-99",
        route_target="Sales Management",
        currency="AUD",
    )
    assert resolve_sales_document_type(inv, document_types=catalog) == "invoice"
