
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Contract documents must classify to contract DT, not GRN catch-alls."""

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.extraction.document_heading_utils import extract_document_heading_signals
from app.services.classification.document_type_classifier import classify_document_type
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.rule_engine import eval_condition_group_generic, sanitize_condition_group


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _org_dt03() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-03",
        title="Goods receipt note",
        shortTitle="GRN",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_grn"], llm_prompt="GRN",
        routeTarget="Purchase Management",
        purchaseBundleRole="grn",
        classifier=DocumentTypeClassifier.model_validate(
            {
                "enabled": True,
                "priority": 18,
                "confidence": 0.93,
                "root": {
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "group",
                            "operator": "OR",
                            "children": [
                                {
                                    "type": "condition",
                                    "field": "document_text",
                                    "operator": "regex",
                                    "value": "(?i)(goods\\s+receipt|delivery\\s+(note|docket)|\\bGRN\\b)",
                                },
                                {
                                    "type": "condition",
                                    "field": "has_heading_grn",
                                    "operator": "equals",
                                    "value": "true",
                                },
                            ],
                        },
                        {
                            "type": "condition",
                            "field": "has_invoice_no",
                            "operator": "equals",
                            "value": "false",
                        },
                        {
                            "type": "condition",
                            "field": "is_commercial_invoice",
                            "operator": "equals",
                            "value": "false",
                        },
                    ],
                },
            }
        ),
    )


def _org_dt04() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-04",
        title="Recurring / contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Vault",
        classifier=DocumentTypeClassifier.model_validate(
            {
                "enabled": True,
                "priority": 15,
                "confidence": 0.85,
                "root": {
                    "type": "group",
                    "operator": "OR",
                    "children": [
                        {
                            "type": "condition",
                            "field": "has_heading_contract",
                            "operator": "equals",
                            "value": "true",
                        },
                        {
                            "type": "group",
                            "operator": "AND",
                            "children": [
                                {
                                    "type": "condition",
                                    "field": "has_invoice_no",
                                    "operator": "equals",
                                    "value": "false",
                                },
                                {
                                    "type": "group",
                                    "operator": "OR",
                                    "children": [
                                        {
                                            "type": "condition",
                                            "field": "document_text",
                                            "operator": "regex",
                                            "value": "(?i)(docusign|master service agreement|service agreement|lease agreement|statement of work)",
                                        },
                                        {
                                            "type": "condition",
                                            "field": "document_text",
                                            "operator": "regex",
                                            "value": "(?i)\\bcontract\\b",
                                        },
                                        {
                                            "type": "condition",
                                            "field": "document_text",
                                            "operator": "contains",
                                            "value": "terms and conditions",
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            }
        ),
    )


def test_contract_heading_detected_for_spot_purchase_title() -> None:
    text = (
        "Docusign Envelope ID: AA78275A-2306-89AA-8362-377F39422845\n"
        "CONTRACT FOR SPOT PURCHASE/SALE OF ENVIRONMENTAL PRODUCTS\n"
        "CONTRACT DETAILS"
    )
    signals = extract_document_heading_signals(text)
    assert signals.has_heading_contract is True
    assert signals.primary_kind == "contract"


def test_grn_classifier_does_not_match_contract_without_grn_signals() -> None:
    from app.services.classification.document_type_rule_engine import (
        build_document_classifier_context,
        _document_field,
    )

    body = (
        "Docusign Envelope ID: AA78275A\n"
        "CONTRACT FOR SPOT PURCHASE/SALE OF ENVIRONMENTAL PRODUCTS\n"
        "terms and conditions"
    )
    invoice = _invoice(email_attachment_name="4752d7ef-d348-4433-8228-26da345ace96.pdf")
    parsed = InvoiceData(document_text=body)
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    resolver = lambda field: _document_field(ctx, field)
    root = _org_dt03().classifier.root
    assert eval_condition_group_generic(root, field_resolver=resolver) is False


def test_contract_classifies_to_dt04_for_upload_whatsapp_and_email() -> None:
    body = (
        "Docusign Envelope ID: AA78275A-2306-89AA-8362-377F39422845\n"
        "CONTRACT FOR SPOT PURCHASE/SALE OF ENVIRONMENTAL PRODUCTS\n"
        "terms and conditions"
    )
    document_types = [_org_dt04(), _org_dt03()]
    channels = [
        ("upload", "upload@local"),
        ("whatsapp", "whatsapp:+61400000000"),
        ("email", "legal@vendor.com"),
    ]
    for _label, sender in channels:
        result = classify_document_type(
            invoice=_invoice(
                email_attachment_name="4752d7ef-d348-4433-8228-26da345ace96.pdf",
                email_sender=sender,
            ),
            parsed=InvoiceData(document_text=body),
            document_types=document_types,
            parse_confidence="high",
        )
        assert result.code == "DT-04", f"expected DT-04 for {_label}, got {result.code}"


def test_sanitize_condition_group_drops_empty_or_branch() -> None:
    root = {
        "type": "group",
        "operator": "OR",
        "children": [
            {
                "type": "group",
                "operator": "AND",
                "children": [],
            },
            {
                "type": "condition",
                "field": "has_invoice_no",
                "operator": "equals",
                "value": "false",
            },
        ],
    }
    sanitized = sanitize_condition_group(root)
    assert len(sanitized["children"]) == 1
