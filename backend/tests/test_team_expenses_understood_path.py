"""Understood-path Team Expenses: catalogue-driven route, not hardcoded DT-12."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import (
    EmailCaptureAction,
    EmailCaptureRule,
    PostToAccounts,
    RuleBookConfigPayload,
    TeamExpenseMatchOn,
    TeamExpensePolicy,
    TeamExpenseRule,
)
from app.services.classification.document_type_catalog import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    is_team_expenses_document_type,
    resolved_route_for_definition,
    route_target_for_document_type,
    team_expenses_document_types,
)
from app.services.dossier.dossier_approval_service import build_dossier_approval_chain
from app.services.invoice.invoice_evaluation_service import evaluate_invoice_routing
from app.services.invoice.vision_document_type_map import (
    has_strong_team_expense_claim_evidence,
    _pool_excluding_team_expenses_without_claim,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _dt(
    *,
    code: str,
    title: str = "Doc",
    route: str = "",
    playbook: str = "",
    enabled: bool = True,
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        shortTitle=title[:20],
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=[],
        llmPrompt="",
        routeTarget=route or "Vault",
        enabled=enabled,
        playbookProfile=playbook,
    )


def test_custom_employee_claim_dt_resolves_team_expenses() -> None:
    # Vault route_target + employee_claim playbook still resolves to Team Expenses
    custom = _dt(code="TE-01", title="Staff claim", route="Vault", playbook="employee_claim")
    assert resolved_route_for_definition(custom) == ROUTE_TEAM
    assert is_team_expenses_document_type(custom)
    assert route_target_for_document_type("TE-01", [custom]) == ROUTE_TEAM


def test_explicit_route_target_any_code() -> None:
    custom = _dt(code="CLAIM-99", title="Reimburse", route=ROUTE_TEAM)
    assert is_team_expenses_document_type(custom)
    assert "CLAIM-99" in {d.code for d in team_expenses_document_types([custom])}


def test_purchase_dt_not_team_even_with_employee_like_title() -> None:
    tax = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    assert not is_team_expenses_document_type(tax)


def test_ensure_keeps_claim_dt_for_against_advance_heading() -> None:
    """Legacy 'against advance' headings resolve as expense_claim; stay on claim DT."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.purchase.team_expense_kind_service import (
        document_type_team_expense_kind,
    )
    from app.services.purchase.team_expense_route_policy import (
        ensure_team_expenses_document_type,
        infer_preferred_team_expense_kind,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    types = [
        _dt(
            code="DT-08",
            title="Employee expense claim",
            route=ROUTE_TEAM,
            playbook="employee_claim",
        ).model_copy(update={"team_expense_kind": "expense_claim"}),
        DocumentTypeDefinition(
            code="DT-10",
            title="Expense against advance",
            shortTitle="Against",
            klass="Transactional",
            posting="Yes",
            recognitionMode="signals",
            recognitionSignals=[],
            llmPrompt="",
            routeTarget=ROUTE_TEAM,
            enabled=True,
            playbookProfile="employee_claim",
            # Legacy pin is rejected / cleared on the DT schema.
            teamExpenseKind="expense_against_advance",
        ),
    ]
    assert types[1].team_expense_kind == ""

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-08",
        document_heading="EXPENSE CLAIM AGAINST ADVANCE",
        llm_suggested_dt="DT-10",
        capture_source="email",
        email_sender="codevishnu321@gmail.com",
    )
    assert infer_preferred_team_expense_kind(inv, types) == "expense_claim"
    chosen = ensure_team_expenses_document_type(inv, types)
    assert chosen is not None
    assert chosen.code == "DT-08"
    assert inv.document_type_code == "DT-08"
    assert document_type_team_expense_kind(chosen) == "expense_claim"


def test_force_dt_route_blocks_email_and_team_category_override() -> None:
    claim_dt = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    expense_dt = _dt(code="EXP-01", title="Utility bill", route=ROUTE_EXPENSES)

    email_rule = EmailCaptureRule(
        id="ec-team",
        name="Force team via email",
        enabled=True,
        priority=1,
        mailbox="expenses@example.com",
        root={
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "condition",
                    "field": "subject",
                    "operator": "contains",
                    "value": "receipt",
                }
            ],
        },
        action=EmailCaptureAction(save_attachment=True, route_to=ROUTE_TEAM, tags=[]),
    )
    team_rule = TeamExpenseRule(
        id="tr-uber",
        name="Uber",
        enabled=True,
        match_on=TeamExpenseMatchOn(merchant_contains="Uber"),
        post_to=PostToAccounts(ledger="Travel Expense", sub_ledger="Ground Transport"),
        policy=TeamExpensePolicy(auto_approve_below=50),
    )
    config = RuleBookConfigPayload(
        document_types=[expense_dt, claim_dt],
        email_capture_rules=[email_rule],
        team_expense_rules=[team_rule],
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber",
        total=Decimal("12.00"),
        document_type_code="EXP-01",
        document_type_confidence=0.95,
        email_sender="alice@acme.com",
        email_subject="receipt",
        capture_source="email",
        status=InvoiceStatus.PARSING,
        file_hash="force-dt-1",
    )
    result = evaluate_invoice_routing(inv, config, force_dt_route=True)
    assert result.route_target == ROUTE_EXPENSES
    assert "dt:EXP-01" in result.matched_rule_ids


def test_upload_claim_dt_never_team_expenses() -> None:
    claim = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    expense = _dt(code="EXP-01", title="Utility", route=ROUTE_EXPENSES)
    config = RuleBookConfigPayload(document_types=[claim, expense])
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber",
        total=Decimal("42.00"),
        document_type_code="TE-01",
        document_type_confidence=0.99,
        email_sender="priya@acme.com",
        capture_source="upload",
        status=InvoiceStatus.PARSING,
        file_hash="upload-te-block",
    )
    result = evaluate_invoice_routing(inv, config, force_dt_route=True)
    assert result.route_target != ROUTE_TEAM
    assert "policy:te_blocked_upload" in result.matched_rule_ids


def test_email_employee_sender_forces_team_even_if_purchase_dt() -> None:
    from app.schemas.rule_book_config import EmployeeMaster

    purchase = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    claim = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    employee = EmployeeMaster(
        id="e1",
        name="Priya Nair",
        email="priya@acme.com",
        status="Active",
    )
    config = RuleBookConfigPayload(
        document_types=[purchase, claim],
        employee_masters=[employee],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Cafe",
        total=Decimal("40.00"),
        document_type_code="AP-01",
        document_type_confidence=0.95,
        email_sender="priya@acme.com",
        capture_source="email",
        status=InvoiceStatus.PARSING,
        file_hash="emp-force-te",
    )
    result = evaluate_invoice_routing(inv, config, force_dt_route=True)
    assert result.route_target == ROUTE_TEAM
    assert "policy:te_employee_sender" in result.matched_rule_ids
    assert (inv.document_type_code or "").upper() == "TE-01"


def test_email_unknown_sender_not_forced_team() -> None:
    from app.schemas.rule_book_config import EmployeeMaster

    purchase = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    claim = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    config = RuleBookConfigPayload(
        document_types=[purchase, claim],
        employee_masters=[
            EmployeeMaster(id="e1", name="Priya", email="priya@acme.com", status="Active")
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Cafe",
        total=Decimal("40.00"),
        document_type_code="AP-01",
        document_type_confidence=0.95,
        email_sender="vendor@example.com",
        capture_source="email",
        status=InvoiceStatus.PARSING,
        file_hash="unknown-sender",
    )
    result = evaluate_invoice_routing(inv, config)
    assert result.route_target == ROUTE_PURCHASE
    assert "policy:te_employee_sender" not in result.matched_rule_ids


def test_whatsapp_employee_forces_team() -> None:
    from app.schemas.rule_book_config import EmployeeMaster

    purchase = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    claim = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    employee = EmployeeMaster(
        id="e1",
        name="Priya Nair",
        email="priya@acme.com",
        whatsapp_number="+61 412 345 678",
        status="Active",
    )
    config = RuleBookConfigPayload(
        document_types=[purchase, claim],
        employee_masters=[employee],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber",
        total=Decimal("25.00"),
        document_type_code="AP-01",
        document_type_confidence=0.9,
        email_sender="+61412345678",
        capture_source="whatsapp",
        status=InvoiceStatus.PARSING,
        file_hash="wa-force-te",
    )
    result = evaluate_invoice_routing(inv, config)
    assert result.route_target == ROUTE_TEAM
    assert "policy:te_employee_sender" in result.matched_rule_ids


def test_upload_excludes_team_dt_from_classifier_pool() -> None:
    team = _dt(code="TE-01", title="Claim", route=ROUTE_TEAM, playbook="employee_claim")
    purchase = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="X",
        status=InvoiceStatus.PARSING,
        file_hash="upload-pool",
        capture_source="upload",
    )
    filtered = _pool_excluding_team_expenses_without_claim(
        [team, purchase],
        heading_kind="expense_claim",
        document_heading="EXPENSE CLAIM",
        canonical_document_type="",
        invoice=inv,
    )
    assert [d.code for d in filtered] == ["AP-01"]


def test_strong_claim_evidence_requires_explicit_cues() -> None:
    assert has_strong_team_expense_claim_evidence(
        document_heading="EXPENSE CLAIM",
        canonical_document_type="",
    )
    assert has_strong_team_expense_claim_evidence(
        document_heading="",
        canonical_document_type="Staff reimbursement",
    )
    assert not has_strong_team_expense_claim_evidence(
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
    )
    # Bare "meal" is not enough
    assert not has_strong_team_expense_claim_evidence(
        document_heading="Meal receipt",
        canonical_document_type="",
    )


def test_invoice_like_pool_excludes_team_without_claim_cues() -> None:
    team = _dt(code="TE-01", title="Claim", route=ROUTE_TEAM, playbook="employee_claim")
    purchase = _dt(code="AP-01", title="Tax Invoice", route=ROUTE_PURCHASE)
    filtered = _pool_excluding_team_expenses_without_claim(
        [team, purchase],
        heading_kind="tax_invoice",
        document_heading="TAX INVOICE",
        canonical_document_type="Tax Invoice",
        invoice=None,
    )
    assert [d.code for d in filtered] == ["AP-01"]

    kept = _pool_excluding_team_expenses_without_claim(
        [team, purchase],
        heading_kind="tax_invoice",
        document_heading="EXPENSE CLAIM FORM",
        canonical_document_type="",
        invoice=None,
    )
    assert {d.code for d in kept} == {"TE-01", "AP-01"}


@pytest.mark.asyncio
async def test_dossier_chain_pending_on_team_expense_approval(
    db_session: AsyncSession,
) -> None:
    claim = _dt(code="TE-01", title="Staff claim", route=ROUTE_TEAM, playbook="employee_claim")
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber",
        total=Decimal("80.00"),
        route_target=ROUTE_TEAM,
        document_type_code="TE-01",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        file_hash="dossier-team-gate",
    )
    db_session.add(inv)
    await db_session.flush()

    logs_continued = [
        AuditLog(
            event="vision_understand_passed",
            invoice_id=inv.id,
            created_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
            detail={"can_understand": True},
        ),
        AuditLog(
            event="vision_posting_continued",
            invoice_id=inv.id,
            created_at=datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="team_expense_approval_required",
            invoice_id=inv.id,
            created_at=datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc),
            detail={"amount": 80.0, "auto_approve_below": 30.0},
        ),
    ]
    chain = await build_dossier_approval_chain(
        db_session,
        inv,
        logs_continued,
        definition=claim,
        payment=None,
        published=False,
        pipeline_path="understood",
    )
    assert chain.policy_mode == "manager_gate"
    gate = next(step for step in chain.steps if step.id == "document_gate")
    assert gate.state == "pending"
    assert "manager" in (gate.detail or "").lower() or "Waiting" in (gate.detail or "")
