"""Tests for per-DT playbook profile resolution and approval gate."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_approval_service import apply_document_type_approval_gate
from app.services.document_type_playbook_profile_service import (
    effective_approval_policy,
    effective_match_policy,
    effective_playbook_profile,
    should_enforce_bundle_mandatory,
)
from app.services.routing_review_service import requires_playbook_review
from app.services.validator import ValidationResult


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
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
    from app.services.document_type_playbook_service import split_bundle_items

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


def test_playbook_review_skipped_when_bundle_not_enforced() -> None:
    from app.services.document_type_playbook_service import PlaybookGateResult

    playbook = PlaybookGateResult(
        missing_bundle_mandatory=("DT-14",),
        missing_bundle_conditional_dt=(),
        conditional_advisories=(),
        missing_extraction_fields=(),
    )
    definition = _definition(code="DT-03", playbookProfile="direct_expense")
    assert requires_playbook_review(playbook, definition=definition) is False
    assert requires_playbook_review(playbook, definition=_definition(playbookProfile="po_goods")) is True


@pytest.mark.asyncio
async def test_direct_expense_approval_gate_holds_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
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
        "app.services.document_type_approval_service.log_event",
        AsyncMock(),
    )

    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[ValidationResult("VR03", True, "ok")],
    )
    assert held is True


@pytest.mark.asyncio
async def test_po_goods_touchless_passes_clean_match() -> None:
    definition = _definition(playbookProfile="po_goods")
    invoice = MagicMock()
    invoice.id = 7
    invoice.route_target = "Purchase Management"

    session = AsyncMock()
    held = await apply_document_type_approval_gate(
        session,
        invoice,
        definition=definition,
        validation_results=[ValidationResult("VR15", True, "3-Way Match")],
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
                    "fraudRisk": "low",
                    "oneLine": "test",
                    "routeTarget": "Purchase Management",
                }
            ]
        }
    )
    assert payload.document_types[0].playbook_profile == "standard_transactional"
