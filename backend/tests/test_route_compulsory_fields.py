"""Route compulsory field baseline tests."""

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.route_compulsory_fields import (
    merge_route_compulsory_into_document_type,
    route_compulsory_baseline,
)


def _dt(**kwargs: object) -> DocumentTypeDefinition:
    base = {
        "code": "DT-12",
        "title": "Employee claim",
        "short_title": "Claim",
        "klass": "Transactional",
        "posting": "Yes",
        "route_target": "Sales Management",
        "playbook_profile": "employee_claim",
        "required_fields": ["vendor", "total"],
        "extraction_fields": ["vendor", "invoice_no", "total"],
    }
    base.update(kwargs)
    return DocumentTypeDefinition.model_validate(base)


def test_sales_route_baseline_includes_subtotal_and_gst() -> None:
    assert route_compulsory_baseline("Sales Management") == [
        "vendor",
        "subtotal",
        "gst",
        "total",
        "due_date",
    ]


def test_merge_adds_missing_route_recommendations_for_dt12() -> None:
    merged = merge_route_compulsory_into_document_type(_dt())
    assert set(merged.required_fields) == {
        "vendor",
        "subtotal",
        "gst",
        "total",
        "due_date",
    }
    assert "subtotal" in merged.extraction_fields
    assert "gst" in merged.extraction_fields
    assert "due_date" in merged.extraction_fields


def test_merge_skips_vault_route() -> None:
    merged = merge_route_compulsory_into_document_type(
        _dt(
            route_target="Vault",
            posting="No",
            playbook_profile="non_actionable",
            required_fields=[],
            extraction_fields=["document_heading"],
        )
    )
    assert merged.required_fields == []


def test_merge_skips_non_transactional_playbook_profile() -> None:
    merged = merge_route_compulsory_into_document_type(
        _dt(
            playbook_profile="reconciliation",
            required_fields=["invoice_no"],
            extraction_fields=["invoice_no"],
        )
    )
    assert merged.required_fields == ["invoice_no"]
    assert "subtotal" not in merged.extraction_fields
