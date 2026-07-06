
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Classifier trees drive policy scoring when configured."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.rule_book_config import RuleCondition, RuleConditionGroup
from app.services.classification.finance_dt_policy_scorer import score_all_enabled_dts
from app.services.invoice.invoice_data import InvoiceData


def test_policy_scorer_uses_classifier_tree_when_configured() -> None:
    invoice = Invoice(id=1, tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PARSING, currency="AUD")
    parsed = InvoiceData(
        vendor="Permagen",
        document_text="CONTRACT FOR FORWARD PURCHASE\nSIGNED for and on behalf",
        document_heading="CONTRACT FOR FORWARD PURCHASE",
        invoice_date=date(2026, 4, 10),
        total=Decimal("220000"),
    )
    contract_dt = DocumentTypeDefinition(
        code="DT-27",
        title="Finance contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Vault",
        enabled=True,
        absent_fields=["invoice_no"],
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=20,
            confidence=0.9,
            root=RuleConditionGroup(
                operator="AND",
                children=[
                    RuleCondition(
                        field="document_text",
                        operator="contains",
                        value="CONTRACT FOR FORWARD PURCHASE",
                    ),
                    RuleCondition(field="has_invoice_no", operator="equals", value="false"),
                ],
            ).model_dump(),
        ),
    )
    invoice_dt = DocumentTypeDefinition(
        code="DT-01",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Purchase Management",
        enabled=True,
        required_fields=["vendor", "invoice_no", "total"],
        classifier=DocumentTypeClassifier(enabled=False, priority=100, confidence=0.85),
    )

    policy = score_all_enabled_dts(
        invoice=invoice,
        parsed=parsed,
        document_types=[invoice_dt, contract_dt],
        parse_confidence="high",
    )
    assert policy.winner_dt == "DT-27"
    assert policy.winner_confidence >= 0.65


def test_policy_scorer_accepts_heading_kind_parameter() -> None:
    invoice = Invoice(id=2, tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PARSING, currency="AUD")
    parsed = InvoiceData(
        vendor="Acme",
        document_text="PURCHASE ORDER\nPO Number: PO-9001",
        document_heading="PURCHASE ORDER",
    )
    po_dt = DocumentTypeDefinition(
        code="DT-14",
        title="Purchase order",
        shortTitle="PO",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Purchase Management",
        enabled=True,
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=30,
            confidence=0.9,
            root=RuleConditionGroup(
                operator="AND",
                children=[
                    RuleCondition(field="document_text", operator="contains", value="purchase order"),
                ],
            ).model_dump(),
        ),
    )
    policy = score_all_enabled_dts(
        invoice=invoice,
        parsed=parsed,
        document_types=[po_dt],
        parse_confidence="high",
        heading_kind="purchase_order",
    )
    assert policy.winner_dt == "DT-14"
