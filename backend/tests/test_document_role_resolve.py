"""Role-first DT discrimination tests."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_role_resolve_service import (
    definition_matches_role,
    filter_document_types_for_role,
    heading_role_conflicts_with_definition,
    resolve_document_role,
    role_from_heading_kind,
)
from app.services.invoice.vision_document_type_map import map_vision_label_to_document_type


def _dt(
    *,
    code: str,
    title: str,
    short_title: str | None = None,
    playbook: str = "",
    posting: str = "Yes",
    purchase_role: str = "",
    sales_role: str = "",
    recognition_signals: list[str] | None = None,
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        shortTitle=short_title or title,
        klass="Transactional" if posting == "Yes" else "Supporting",
        posting=posting,
        recognitionMode="signals",
        recognitionSignals=recognition_signals or [],
        llmPrompt="",
        routeTarget="Purchase Management",
        playbookProfile=playbook,
        purchaseBundleRole=purchase_role,
        salesBundleRole=sales_role,
        enabled=True,
        classifier={"enabled": False, "priority": 100, "confidence": 0.85},
    )


def test_role_from_heading_kinds() -> None:
    assert role_from_heading_kind("purchase_order") == "po"
    assert role_from_heading_kind("grn") == "grn"
    assert role_from_heading_kind("delivery_note") == "dn"
    assert role_from_heading_kind("tax_invoice") == "invoice"


def test_vision_map_delivery_note_selects_sales_dn_not_grn() -> None:
    catalogue = [
        _dt(
            code="DT-04",
            title="Goods receipt note (GRN)",
            playbook="supporting",
            posting="No",
            purchase_role="grn",
            recognition_signals=["heading_grn"],
        ),
        DocumentTypeDefinition(
            code="DT-06",
            title="Delivery note",
            shortTitle="Delivery note",
            klass="Supporting",
            posting="No",
            recognitionMode="signals",
            recognitionSignals=["heading_delivery_note"],
            llmPrompt="",
            routeTarget="Sales Management",
            playbookProfile="supporting",
            purchaseBundleRole="",
            salesBundleRole="dn",
            enabled=True,
            classifier={"enabled": False, "priority": 100, "confidence": 0.85},
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="DELIVERY NOTE",
        canonical_document_type="Delivery Note",
        document_types=catalogue,
        filename="S2_DN_Harbour_SO-TEST-001.pdf",
    )
    assert result.heading_kind == "delivery_note"
    assert result.code == "DT-06"
    assert result.reason == "matched"


def test_vision_map_sales_tax_invoice_prefers_sales_route() -> None:
    from types import SimpleNamespace

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="Non-PO vendor invoice",
            shortTitle="Non-PO invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="signals",
            recognitionSignals=["heading_invoice", "heading_tax_invoice"],
            llmPrompt="",
            routeTarget="Purchase Management",
            playbookProfile="standard_transactional",
            enabled=True,
            classifier={"enabled": False, "priority": 100, "confidence": 0.85},
        ),
        DocumentTypeDefinition(
            code="DT-07",
            title="Customer tax invoice (outbound AR)",
            shortTitle="Customer invoice",
            klass="Transactional",
            posting="Yes",
            recognitionMode="signals",
            recognitionSignals=["heading_invoice", "heading_tax_invoice"],
            llmPrompt="",
            routeTarget="Sales Management",
            playbookProfile="ar_goods",
            enabled=True,
            classifier={"enabled": False, "priority": 100, "confidence": 0.85},
        ),
    ]
    invoice = SimpleNamespace(
        extracted_fields={"perspective": "sales", "llm_perspective": "sales"},
        email_attachment_name="S3_INV_Harbour_SO-TEST-001_CLEAN.pdf",
        purchase_document_type=None,
        sales_document_type=None,
        document_text=None,
    )
    result = map_vision_label_to_document_type(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
        filename="S3_INV_Harbour_SO-TEST-001_CLEAN.pdf",
        invoice=invoice,
    )
    assert result.heading_kind == "tax_invoice"
    assert result.code == "DT-07"
    assert result.reason == "matched"


def test_filename_resolves_po_role() -> None:
    assert resolve_document_role(filename="P1_PO_Everest_PO-TEST-001.pdf") == "po"
    assert resolve_document_role(filename="P2_GRN_Everest_PO-TEST-001.pdf") == "grn"
    assert resolve_document_role(filename="P3_INV_Everest_CLEAN.pdf") == "invoice"


def test_po_heading_conflicts_with_po_goods_invoice() -> None:
    po_goods = _dt(
        code="DT-03",
        title="PO-based goods invoice",
        playbook="po_goods",
        posting="Yes",
        recognition_signals=["heading_invoice", "has_po_reference"],
    )
    supporting_po = _dt(
        code="DT-02",
        title="Purchase order (copy)",
        playbook="supporting",
        posting="No",
        purchase_role="po",
        recognition_signals=["heading_purchase_order"],
    )
    assert heading_role_conflicts_with_definition("purchase_order", po_goods) is True
    assert heading_role_conflicts_with_definition("purchase_order", supporting_po) is False
    assert definition_matches_role(supporting_po, "po") is True
    assert definition_matches_role(po_goods, "po") is False


def test_vision_map_po_heading_selects_supporting_not_po_goods() -> None:
    catalogue = [
        _dt(
            code="DT-03",
            title="PO-based goods invoice",
            playbook="po_goods",
            posting="Yes",
            recognition_signals=["heading_invoice", "has_po_reference"],
        ),
        _dt(
            code="DT-02",
            title="Purchase order (copy)",
            playbook="supporting",
            posting="No",
            purchase_role="po",
            recognition_signals=["heading_purchase_order"],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="PURCHASE ORDER",
        canonical_document_type="Purchase Order",
        document_types=catalogue,
        filename="P1_PO_Everest_PO-TEST-001.pdf",
    )
    assert result.code == "DT-02"
    assert result.reason == "matched"
    assert result.heading_kind == "purchase_order"


def test_vision_map_po_heading_holds_when_no_po_role_dt() -> None:
    catalogue = [
        _dt(
            code="DT-03",
            title="PO-based goods invoice",
            playbook="po_goods",
            posting="Yes",
            recognition_signals=["heading_invoice"],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="PURCHASE ORDER",
        canonical_document_type="Purchase Order",
        document_types=catalogue,
    )
    assert result.code is None
    assert result.reason == "no_dt_for_role_po"


def test_vision_map_tax_invoice_still_picks_commercial() -> None:
    catalogue = [
        _dt(
            code="DT-02",
            title="Purchase order (copy)",
            playbook="supporting",
            posting="No",
            purchase_role="po",
        ),
        _dt(
            code="DT-01",
            title="PO-based goods invoice",
            playbook="po_goods",
            posting="Yes",
            recognition_signals=["heading_invoice", "heading_tax_invoice"],
        ),
    ]
    result = map_vision_label_to_document_type(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        document_types=catalogue,
        filename="P3_INV_Everest.pdf",
    )
    assert result.code == "DT-01"
    assert result.heading_kind == "tax_invoice"


def test_filter_for_grn_excludes_invoice() -> None:
    catalogue = [
        _dt(code="DT-04", title="GRN", playbook="supporting", posting="No", purchase_role="grn"),
        _dt(code="DT-01", title="Invoice", playbook="po_goods", posting="Yes"),
    ]
    filtered = filter_document_types_for_role(catalogue, "grn")
    assert [d.code for d in filtered] == ["DT-04"]
