"""Org-owned classifiers are preserved — shipped templates are not merged in."""

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import DocumentClassificationConfig, validate_rule_book_config_payload
from app.services.document_type_catalog import load_shipped_default_document_types
from app.services.document_type_classifier import classify_document_type
from app.services.invoice_data import InvoiceData


def _simplified_org_config() -> dict:
    types = [item.model_dump(mode="json") for item in load_shipped_default_document_types()]
    for row in types:
        if row.get("code") == "DT-16":
            row["classifier"] = {
                "enabled": True,
                "priority": 20,
                "confidence": 0.85,
                "root": {
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "condition",
                            "field": "attachment_name",
                            "operator": "contains",
                            "value": "contract",
                        }
                    ],
                },
            }
    return {"schema_version": 1, "document_types": types}


def test_org_classifier_not_upgraded_from_shipped_template() -> None:
    config = validate_rule_book_config_payload(_simplified_org_config())
    dt16 = next(item for item in config.document_types if item.code == "DT-16")
    root = dt16.classifier.root
    children = root.children if hasattr(root, "children") else root.get("children", [])
    assert len(children) == 1


def test_unclassified_forces_review_below_route_threshold() -> None:
    config = validate_rule_book_config_payload(_simplified_org_config())
    result = classify_document_type(
        invoice=Invoice(
            id=2,
            org_id=1,
            status=InvoiceStatus.PARSING,
            currency="AUD",
            email_attachment_name="random-upload.pdf",
        ),
        parsed=InvoiceData(vendor="Unknown Co", document_text="misc memo"),
        document_types=config.document_types,
        unclassified=DocumentClassificationConfig(unclassified_document_type_code="DT-24"),
    )
    assert result.code == "DT-24"
    assert result.needs_review is True
    assert "No classifier matched" in result.reason
