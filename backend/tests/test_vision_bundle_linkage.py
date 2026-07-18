"""Unit tests for vision-path soft bundle linkage priority."""

from __future__ import annotations

from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.vision_bundle_linkage import (
    persist_vision_bundle_snapshot,
    resolve_vision_bundle_key,
    should_use_vision_bundle_linkage,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _inv(**kwargs) -> Invoice:
    base = dict(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
    )
    base.update(kwargs)
    return Invoice(**base)


def test_priority_invoice_no_wins_over_po_and_so() -> None:
    link = resolve_vision_bundle_key(
        _inv(
            invoice_no="INV-1",
            po_reference="PO-99",
            so_reference="SO-88",
            extracted_fields={"proforma_invoice_no": "PI-1", "other_reference": "SHIP-1"},
        ),
        custom_field_key="other_reference",
    )
    assert link.kind == "invoice_no"
    assert link.key == "INV-1"


def test_priority_proforma_when_no_invoice_no() -> None:
    link = resolve_vision_bundle_key(
        _inv(
            invoice_no=None,
            po_reference="PO-99",
            extracted_fields={"proforma_invoice_no": "PI-42"},
        ),
        custom_field_key="other_reference",
    )
    assert link.kind == "proforma_invoice_no"
    assert link.key == "PI-42"


def test_priority_po_when_no_invoice_or_proforma() -> None:
    link = resolve_vision_bundle_key(
        _inv(invoice_no=None, po_reference="PO-100", so_reference="SO-1"),
        custom_field_key="other_reference",
    )
    assert link.kind == "po_reference"
    assert link.key == "PO-100"


def test_priority_so_when_no_higher_keys() -> None:
    link = resolve_vision_bundle_key(
        _inv(invoice_no=None, po_reference=None, so_reference="SO-55"),
        custom_field_key="other_reference",
    )
    assert link.kind == "so_reference"
    assert link.key == "SO-55"


def test_priority_custom_field_last() -> None:
    link = resolve_vision_bundle_key(
        _inv(
            invoice_no=None,
            po_reference=None,
            so_reference=None,
            extracted_fields={"other_reference": "LC-77"},
        ),
        custom_field_key="other_reference",
    )
    assert link.kind == "custom"
    assert link.key == "LC-77"
    assert link.custom_field_key == "other_reference"


def test_standalone_when_no_keys() -> None:
    link = resolve_vision_bundle_key(
        _inv(invoice_no=None, po_reference=None, so_reference=None),
        custom_field_key="other_reference",
    )
    assert link.kind == "none"
    assert link.key is None
    assert not link.has_key


def test_custom_skipped_when_org_key_unset() -> None:
    link = resolve_vision_bundle_key(
        _inv(
            invoice_no=None,
            extracted_fields={"other_reference": "LC-77"},
        ),
        custom_field_key=None,
    )
    assert link.kind == "none"


def test_persist_snapshot_and_should_use_flag() -> None:
    inv = _inv(invoice_no="INV-9")
    link = resolve_vision_bundle_key(inv)
    persist_vision_bundle_snapshot(inv, link)
    assert inv.extracted_fields["vision_bundle_kind"] == "invoice_no"
    assert inv.extracted_fields["vision_bundle_key"] == "INV-9"
    assert should_use_vision_bundle_linkage(inv) is True


def test_should_use_vision_vaulted_and_header_review() -> None:
    vaulted = _inv(evaluation_status="vision_vaulted", invoice_no="INV-V")
    review = _inv(evaluation_status="vision_header_review", invoice_no="INV-R")
    assert should_use_vision_bundle_linkage(vaulted) is True
    assert should_use_vision_bundle_linkage(review) is True


def test_should_use_false_when_classified() -> None:
    inv = _inv(
        evaluation_status="needs_review",
        document_type_code="DT-01",
        extracted_fields={"vision_bundle_key": "INV-1", "vision_bundle_kind": "invoice_no"},
    )
    assert should_use_vision_bundle_linkage(inv) is False
