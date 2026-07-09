"""Tests for per-DT playbook profile resolution and approval gate."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_approval_service import apply_document_type_approval_gate
from app.services.classification.document_type_playbook_profile_service import (
    effective_approval_policy,
    effective_match_policy,
    effective_playbook_profile,
    should_enforce_bundle_mandatory,
)
from app.services.invoice.routing_review_service import requires_playbook_review
from app.services.rule_book.validator import ValidationResult


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Purchase Management",
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_dt01_default_playbook_profile() -> None:
    definition = _definition(playbookProfile="po_goods")
    assert effective_playbook_profile(definition) == "po_goods"
    assert effective_match_policy(definition).mode == "three_way_po_grn"
    assert effective_approval_policy(definition).mode == "touchless_on_clean_match"
    assert should_enforce_bundle_mandatory(definition) is True


def test_dt01_empty_bundle_mandatory_is_user_only() -> None:
    from app.services.classification.document_type_playbook_service import split_bundle_items

    definition = _definition(bundleMandatory=[])
    mandatory, _ = split_bundle_items(definition.bundle_mandatory)
    assert mandatory == []


def test_dt03_direct_expense_profile() -> None:
    definition = _definition(
        code="DT-03",
        playbookProfile="direct_expense",
        absentFields=["po_reference"],
    )
    assert effective_playbook_profile(definition) == "direct_expense"
    assert effective_match_policy(definition).mode == "none"
    assert effective_approval_policy(definition).mode == "full_doa"
    assert should_enforce_bundle_mandatory(definition) is False


def test_explicit_match_policy_override() -> None:
    definition = _definition(matchPolicy={"mode": "none"})
    assert effective_match_policy(definition).mode == "none"


def test_playbook_review_never_blocks_routing() -> None:
    from app.services.classification.document_type_playbook_service import PlaybookGateResult

    playbook = PlaybookGateResult(
        missing_bundle_mandatory=("DT-14",),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=("vendor",),
    )
    definition = _definition(code="DT-03", playbookProfile="direct_expense")
    assert requires_playbook_review(playbook, definition=definition) is False
    assert requires_playbook_review(playbook, definition=_definition(playbookProfile="po_goods")) is False


@pytest.mark.asyncio
async def test_direct_expense_approval_gate_holds_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL

    definition = _definition(code="DT-03", playbookProfile="direct_expense")
    invoice = MagicMock()
    invoice.id = 42
    invoice.status = "validating"
    invoice.evaluation_status = None
    invoice.route_target = "Expenses Management"
    invoice.purchase_document_type = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.log_event",
        AsyncMock(),
    )

    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[ValidationResult("VR03", True, "ok")],
    )
    assert held is True
    assert invoice.evaluation_status == EVAL_PENDING_APPROVAL


@pytest.mark.asyncio
async def test_ar_goods_touchless_passes_audit_match_without_clean_vr15_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition(code="DT-26", playbookProfile="ar_goods", routeTarget="Sales Management")
    invoice = MagicMock()
    invoice.id = 8
    invoice.tenant_id = None
    invoice.route_target = "Sales Management"

    session = AsyncMock()

    async def _fake_audit(*_args, **_kwargs):
        return {"status": "3-Way Match"}

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.latest_audit_detail_after_cycle_reset",
        _fake_audit,
    )

    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False


@pytest.mark.asyncio
async def test_ar_goods_touchless_passes_clean_match(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = _definition(code="DT-26", playbookProfile="ar_goods", routeTarget="Sales Management")
    invoice = MagicMock()
    invoice.id = 8
    invoice.route_target = "Sales Management"

    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.latest_audit_detail_after_cycle_reset",
        AsyncMock(return_value={"status": "3-Way Match"}),
    )
    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False


@pytest.mark.asyncio
async def test_packing_list_attachment_classified_as_dn() -> None:
    from app.models.invoice import SalesDocumentType
    from app.services.sales.sales_document_service import infer_sales_document_type

    invoice = MagicMock()
    invoice.email_attachment_name = "packing_list_INV-42.pdf"
    invoice.document_text = ""
    invoice.invoice_no = None
    invoice.so_reference = None
    invoice.due_date = None
    assert infer_sales_document_type(invoice) == SalesDocumentType.DN.value


@pytest.mark.asyncio
async def test_po_goods_touchless_passes_clean_match(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = _definition(playbookProfile="po_goods")
    invoice = MagicMock()
    invoice.id = 7
    invoice.route_target = "Purchase Management"

    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.latest_audit_detail_after_cycle_reset",
        AsyncMock(return_value={"status": "3-Way Match"}),
    )
    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False


@pytest.mark.asyncio
async def test_variance_workflow_skipped_after_human_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = _definition(
        playbookProfile="po_goods",
        approvalPolicy={"mode": "variance_workflow"},
    )
    invoice = MagicMock()
    invoice.id = 99
    invoice.route_target = "Purchase Management"

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=1)))

    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False


def test_backfill_playbook_profile_on_save() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_payload

    payload = validate_rule_book_config_payload(
        {
            "document_types": [
                {
                    "code": "DT-01",
                    "title": "PO goods invoice",
                    "shortTitle": "PO goods",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "recognition_mode": "signals", "recognition_signals": ["heading_invoice"], "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                }
            ]
        }
    )
    assert payload.document_types[0].playbook_profile == "po_goods"


def test_effective_playbook_profile_uses_code_defaults() -> None:
    assert (
        effective_playbook_profile(
            _definition(
                code="DT-09",
                title="Freight, logistics & customs broker invoice",
                shortTitle="Freight / broker",
                playbookProfile="",
            )
        )
        == "freight_logistics"
    )
    assert (
        effective_playbook_profile(
            _definition(
                code="DT-10",
                title="Import dossier (commercial invoice + customs entry + duty)",
                shortTitle="Import dossier",
                playbookProfile="",
            )
        )
        == "import_dossier"
    )


def test_playbook_preset_catalog_parity() -> None:
    from app.services.classification.playbook_profile_catalog import PROFILE_PRESETS

    assert len(PROFILE_PRESETS) == 19
    assert "ar_goods" in PROFILE_PRESETS
    assert PROFILE_PRESETS["ar_goods"].match_mode == "three_way_so_dn"


def test_sync_stale_match_policy_on_save() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_payload

    payload = validate_rule_book_config_payload(
        {
            "document_types": [
                {
                    "code": "DT-26",
                    "title": "AR goods invoice",
                    "shortTitle": "AR goods",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Sales Management",
                    "playbookProfile": "ar_goods_2way",
                    "matchPolicy": {"mode": "three_way_so_dn"},
                    "approvalPolicy": {"mode": "touchless_on_clean_match"},
                }
            ]
        }
    )
    assert payload.document_types[0].playbook_profile == "ar_goods_2way"
    assert payload.document_types[0].match_policy is not None
    assert payload.document_types[0].match_policy.mode == "two_way_dn_invoice"
    assert payload.document_types[0].approval_policy is not None
    assert payload.document_types[0].approval_policy.mode == "supervisor_on_exception"


def test_infer_ar_goods_routes_to_sales() -> None:
    from app.services.classification.document_type_recognition_signals import infer_document_metadata

    klass, posting, route = infer_document_metadata("ar_goods")
    assert klass == "Transactional"
    assert posting == "Yes"
    assert route == "Sales Management"

    _, _, route_2way = infer_document_metadata("ar_goods_2way")
    assert route_2way == "Sales Management"


def test_apply_sample_proposal_sets_match_policy() -> None:
    from app.schemas.document_type_sample_analysis import DocumentTypeSampleProposal
    from app.services.classification.document_type_sample_analyzer import apply_sample_proposal_to_draft

    draft = _definition(playbookProfile="po_goods", matchPolicy={"mode": "three_way_po_grn"})
    proposal = DocumentTypeSampleProposal(
        recognition_signals=["heading_invoice"],
        extraction_fields=["invoice_no"],
        required_fields=["invoice_no"],
        absent_fields=[],
        playbook_profile="po_services",
        match_mode="two_way_po_ses",
        approval_mode="touchless_on_clean_match",
        min_route_confidence=0.65,
    )
    updated = apply_sample_proposal_to_draft(draft, proposal)
    assert updated.playbook_profile == "po_services"
    assert updated.match_policy is not None
    assert updated.match_policy.mode == "two_way_po_ses"
    assert updated.approval_policy is not None
    assert updated.approval_policy.mode == "touchless_on_clean_match"
