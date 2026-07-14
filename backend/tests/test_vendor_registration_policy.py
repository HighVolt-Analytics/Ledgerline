
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Vendor registration policy — route, document type, and VR12 driven."""

from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.classification.document_type_catalog import ROUTE_PURCHASE, ROUTE_VAULT
from app.services.classification.document_type_validation_service import PROFILE_NON_ACTIONABLE
from app.services.purchase.expense_vendor_policy import vendor_detection_evaluation_status
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_VENDOR,
    evaluate_invoice_routing,
)
from app.services.master_data.vendor_registration_policy import (
    persisted_vendor_confidence,
    vendor_master_check_enabled,
    vendor_registration_required,
)


def test_persisted_vendor_confidence_omits_when_not_applicable() -> None:
    assert persisted_vendor_confidence(confidence=85.0, registration_required=False) is None
    assert persisted_vendor_confidence(confidence=0.0, registration_required=True) == 0.0
    assert persisted_vendor_confidence(confidence=72.5, registration_required=True) == 72.5


def _contract_type() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-CON",
        title="Contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget=ROUTE_VAULT,
        validation_profile="non_actionable",
        playbook_profile="supporting",
        classifier=DocumentTypeClassifier(enabled=True, priority=5, confidence=0.85),
    )


def test_vendor_master_check_disabled_for_non_actionable() -> None:
    assert vendor_master_check_enabled(_contract_type()) is False


def test_vendor_registration_not_required_for_vault_contract() -> None:
    definition = _contract_type()
    assert (
        vendor_registration_required(
            route_target=ROUTE_VAULT,
            document_type=definition,
        )
        is False
    )


def test_vendor_registration_required_for_purchase_when_vr12_on() -> None:
    from app.schemas.validation_rule import ValidationRuleConfig

    definition = DocumentTypeDefinition(
        code="DT-INV",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="Tax invoice",
        routeTarget=ROUTE_PURCHASE,
        validation_rules=[
            ValidationRuleConfig(code="VR12", enabled=True, severity="block"),
        ],
        classifier=DocumentTypeClassifier(enabled=True, priority=10, confidence=0.85),
    )
    assert (
        vendor_registration_required(
            route_target=ROUTE_PURCHASE,
            document_type=definition,
        )
        is True
    )


def test_vendor_registration_required_when_non_actionable_profile_but_vr12_explicit() -> None:
    """Seeded non_actionable profile must not override explicit VR12 on the rule book."""
    from app.schemas.validation_rule import ValidationRuleConfig

    definition = DocumentTypeDefinition(
        code="DT-03",
        title="Goods receipt",
        shortTitle="GRN",
        klass="Non-transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_grn"], llm_prompt="Goods receipt note",
        routeTarget=ROUTE_PURCHASE,
        validation_profile="non_actionable",
        validation_rules=[
            ValidationRuleConfig(code="VR03", enabled=True, severity="block"),
            ValidationRuleConfig(code="VR12", enabled=True, severity="block"),
        ],
        classifier=DocumentTypeClassifier(enabled=True, priority=5, confidence=0.85),
    )
    assert vendor_master_check_enabled(definition) is True
    assert (
        vendor_registration_required(
            route_target=ROUTE_PURCHASE,
            document_type=definition,
        )
        is True
    )


def test_vendor_registration_not_required_when_vr12_disabled() -> None:
    from app.schemas.validation_rule import ValidationRuleConfig

    definition = DocumentTypeDefinition(
        code="DT-INV",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="Tax invoice",
        routeTarget=ROUTE_PURCHASE,
        validation_rules=[
            ValidationRuleConfig(code="VR12", enabled=False, severity="block"),
            ValidationRuleConfig(code="VR03", enabled=True, severity="block"),
        ],
        classifier=DocumentTypeClassifier(enabled=True, priority=10, confidence=0.85),
    )
    assert (
        vendor_registration_required(
            route_target=ROUTE_PURCHASE,
            document_type=definition,
        )
        is False
    )


def test_vendor_detection_skipped_when_registration_not_required() -> None:
    assert (
        vendor_detection_evaluation_status(
            route_target=ROUTE_VAULT,
            confidence=0,
            threshold=70,
            known_master=None,
            amount=1000,
            hold_above=500,
            registration_required=False,
        )
        is None
    )


def test_evaluate_routing_vault_contract_needs_review_not_pending_vendor(
    capture_config,
) -> None:
    from app.models.invoice import Invoice

    contract = _contract_type()
    config = capture_config.model_copy(
        update={"document_types": [*capture_config.document_types, contract]}
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Permagen Pty Ltd",
        invoice_no="CON-001",
        total=Decimal("4000"),
        route_target=ROUTE_VAULT,
        document_type_code="DT-CON",
        document_type_confidence=0.9,
        vendor_confidence=0.0,
        currency="AUD",
    )
    result = evaluate_invoice_routing(inv, config, route_override=ROUTE_VAULT)
    assert result.evaluation_status != EVAL_PENDING_VENDOR
    assert result.evaluation_status == EVAL_AUTO_CODED
    assert result.vendor_confidence is None
