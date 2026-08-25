"""Tests for vision understood-path posting gate."""

from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.invoice_evaluation_service import EVAL_VISION_VAULTED
from app.services.invoice.vision_posting_continue import (
    vision_posting_skip_reason,
    vision_should_continue_posting,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _dt(
    *,
    code: str = "DT-07",
    posting: str = "Yes",
    klass: str = "Transactional",
    route: str = "Purchase Management",
    approval_mode: str | None = None,
) -> DocumentTypeDefinition:
    kwargs: dict = {
        "code": code,
        "title": "Supplier Tax Invoice",
        "shortTitle": "Tax Invoice",
        "klass": klass,
        "posting": posting,
        "recognitionMode": "signals",
        "recognitionSignals": ["heading_invoice"],
        "llmPrompt": "",
        "routeTarget": route,
        "enabled": True,
        "requiredFields": ["vendor", "total"],
        "extractionFields": ["vendor", "total", "currency", "invoice_date"],
    }
    if approval_mode is not None:
        kwargs["approvalPolicy"] = {"mode": approval_mode}
    return DocumentTypeDefinition(**kwargs)


def test_gate_true_for_posting_dt_with_header_ok() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
    )
    assert vision_should_continue_posting(inv, _dt(posting="Yes"), header_ok=True) is True
    assert vision_should_continue_posting(inv, _dt(posting="Conditional"), header_ok=True) is True
    assert (
        vision_should_continue_posting(inv, _dt(posting="Down-payment"), header_ok=True) is True
    )


def test_gate_false_when_header_not_ok() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
    )
    assert vision_should_continue_posting(inv, _dt(), header_ok=False) is False
    assert vision_posting_skip_reason(inv, _dt(), header_ok=False) == "header_not_ok"


def test_non_posting_dt_skip_reason_beats_header_not_ok() -> None:
    """Air Waybill etc.: posting=No is the governing reason, even with empty amounts."""
    from app.services.invoice.vision_posting_continue import vision_hold_evaluation_status

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-06",
    )
    defn = _dt(
        code="DT-06",
        posting="No",
        klass="Non-transactional",
        route="Vault",
    )
    assert vision_should_continue_posting(inv, defn, header_ok=False) is False
    assert vision_posting_skip_reason(inv, defn, header_ok=False) == "dt_not_posting"
    assert (
        vision_hold_evaluation_status(inv, defn, header_ok=False) == EVAL_VISION_VAULTED
    )


def test_posting_dt_incomplete_header_stays_header_review() -> None:
    from app.services.invoice.invoice_evaluation_service import EVAL_VISION_HEADER_REVIEW
    from app.services.invoice.vision_posting_continue import vision_hold_evaluation_status

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
    )
    defn = _dt(posting="Yes")
    assert vision_posting_skip_reason(inv, defn, header_ok=False) == "header_not_ok"
    assert (
        vision_hold_evaluation_status(inv, defn, header_ok=False)
        == EVAL_VISION_HEADER_REVIEW
    )


def test_gate_false_when_no_document_type() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code=None,
    )
    assert vision_should_continue_posting(inv, _dt(), header_ok=True) is False
    assert vision_posting_skip_reason(inv, _dt(), header_ok=True) == "no_document_type"


def test_gate_false_when_definition_missing() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
    )
    assert vision_should_continue_posting(inv, None, header_ok=True) is False
    assert vision_posting_skip_reason(inv, None, header_ok=True) == "definition_missing"


def test_gate_false_for_non_posting_dt() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-02",
    )
    defn = _dt(
        code="DT-02",
        posting="No",
        klass="Non-transactional",
        route="Vault",
    )
    assert vision_should_continue_posting(inv, defn, header_ok=True) is False
    assert vision_posting_skip_reason(inv, defn, header_ok=True) == "dt_not_posting"


def test_gate_false_when_approval_mode_no_posting() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
    )
    defn = _dt(posting="Yes", approval_mode="no_posting")
    assert vision_should_continue_posting(inv, defn, header_ok=True) is False
    assert vision_posting_skip_reason(inv, defn, header_ok=True) == "dt_not_posting"


def test_vision_header_ok_from_invoice_requires_payable_fields() -> None:
    from datetime import date
    from decimal import Decimal

    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice

    defn = _dt(posting="Yes")
    complete = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        vendor="Acme",
        total=Decimal("100"),
    )
    assert vision_header_ok_from_invoice(complete, defn) is True

    incomplete = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        vendor="Acme",
    )
    assert vision_header_ok_from_invoice(incomplete, defn) is False

    needs_review = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        vendor="Acme",
        total=Decimal("100"),
        due_date=date(2026, 6, 1),
        extracted_fields={"needs_review": True},
    )
    # Stale vision needs_review must not block once payable fields are complete.
    assert vision_header_ok_from_invoice(needs_review, defn) is True
    assert (needs_review.extracted_fields or {}).get("needs_review") in (None, False)


def test_vision_posting_skip_message_lists_missing_fields() -> None:
    from app.services.invoice.vision_posting_continue import vision_posting_skip_user_message

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        vendor="Acme",
    )
    msg = vision_posting_skip_user_message(inv, _dt(), header_ok=False)
    assert "total" in msg.lower()
    assert "fields tab" in msg.lower()
    assert "vendor, amounts, dates" not in msg.lower()


def test_header_ok_follows_dt_required_fields_not_hardcoded_vendor() -> None:
    """Advance Requisition (no vendor on the DT) must not block on vendor."""
    from datetime import date
    from decimal import Decimal

    from app.services.invoice.vision_posting_continue import (
        vision_header_gaps,
        vision_header_ok_from_invoice,
    )

    defn = DocumentTypeDefinition(
        code="DT-05",
        title="Advance Requisition",
        shortTitle="Advance",
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=["heading_advance"],
        llmPrompt="",
        routeTarget="Team Expenses",
        teamExpenseKind="advance_requisition",
        enabled=True,
        requiredFields=["total", "currency", "invoice_date"],
        extractionFields=[
            "total",
            "currency",
            "invoice_date",
            "line_items",
            "employee_name",
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-05",
        vendor=None,
        total=Decimal("340000"),
        currency="MMK",
        invoice_date=date(2026, 12, 8),
    )
    assert vision_header_gaps(inv, defn) == []
    assert vision_header_ok_from_invoice(inv, defn) is True


def test_header_gaps_include_vendor_only_when_dt_requires_it() -> None:
    from decimal import Decimal

    from app.services.invoice.vision_posting_continue import vision_header_gaps

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        total=Decimal("100"),
        currency="AUD",
    )
    gaps = vision_header_gaps(inv, _dt())
    assert "vendor" in gaps
    assert "total" not in gaps


def test_expense_claim_header_ok_when_total_only_and_invoice_date() -> None:
    """Cash receipt with one total: persist gst=0 / subtotal, default due_date."""
    from datetime import date
    from decimal import Decimal

    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice

    defn = DocumentTypeDefinition(
        code="DT-04",
        title="Employee expense claim",
        shortTitle="Expense claim",
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=["heading_receipt"],
        llmPrompt="",
        routeTarget="Team Expenses",
        teamExpenseKind="expense_claim",
        enabled=True,
        requiredFields=["vendor", "total", "due_date", "email_sender", "subtotal", "gst"],
        extractionFields=["vendor", "total", "due_date", "email_sender", "subtotal", "gst"],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-04",
        vendor="Bolos",
        total=Decimal("6000"),
        currency="MMK",
        email_sender="ka@example.com",
        invoice_date=date(2026, 5, 18),
        due_date=None,
        subtotal=None,
        gst=None,
    )
    assert vision_header_ok_from_invoice(inv, defn) is True
    assert inv.gst == Decimal("0")
    assert inv.subtotal == Decimal("6000")
    assert inv.due_date == date(2026, 5, 18)


def test_vision_header_ok_from_invoice_requires_payable_fields_incomplete_vendor() -> None:
    from decimal import Decimal

    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice

    defn = _dt(posting="Yes")
    incomplete = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        total=Decimal("100"),
    )
    assert vision_header_ok_from_invoice(incomplete, defn) is False


@pytest.mark.asyncio
async def test_continue_clears_vision_eval_and_sets_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import vision_posting_continue as vpc
    from app.services.tenant.tenant_org_context import OrgContext
    from app.schemas.rule_book_config import RuleBookConfigPayload

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-07",
        evaluation_status=EVAL_VISION_VAULTED,
        route_target="Commercial Invoice",
        vendor="Acme",
    )
    defn = _dt(route="Purchase Management")
    config = RuleBookConfigPayload(document_types=[defn])

    class _Session:
        async def execute(self, _stmt):
            class _R:
                def scalar_one(self_inner):
                    return inv

            return _R()

        async def flush(self):
            return None

        async def get(self, *_a, **_k):
            return None

    async def _noop_sync(*_a, **_k):
        return None

    async def _noop_vendor(*_a, **_k):
        return False

    async def _noop_log(*_a, **_k):
        return None

    async def _fake_validations(*_a, **_k):
        return []

    async def _fake_approval(*_a, **_k):
        return False

    async def _fake_prepare(*_a, **_k):
        return False

    resume_called = {"n": 0}

    async def _fake_resume(session, invoice, *, config=None):
        resume_called["n"] += 1
        assert (invoice.evaluation_status or "") not in {
            EVAL_VISION_VAULTED,
            "vision_header_review",
        }
        assert invoice.route_target == "Purchase Management"

    monkeypatch.setattr(
        "app.services.invoice.pipeline._sync_counterparty_and_evaluate",
        _noop_sync,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._vendor_hold_unless_skipped",
        _noop_vendor,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.prepare_route_register_before_posting",
        _fake_prepare,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.resume_invoice_posting_pipeline",
        _fake_resume,
    )
    monkeypatch.setattr(vpc, "log_event", _noop_log)
    monkeypatch.setattr(vpc, "run_all_validations", _fake_validations)
    monkeypatch.setattr(vpc, "all_passed", lambda _r: True)
    monkeypatch.setattr(vpc, "results_to_json", lambda _r: [])
    monkeypatch.setattr(vpc, "apply_document_type_approval_gate", _fake_approval)
    monkeypatch.setattr(
        "app.services.approval.approval_pipeline_service.human_approved_payable_bypass",
        _noop_vendor,
    )

    await vpc.continue_vision_understood_posting(
        _Session(),  # type: ignore[arg-type]
        inv,
        config=config,
        org=OrgContext(legal_name="Tenant"),
        definition=defn,
    )
    assert resume_called["n"] == 1
    assert inv.route_target == "Purchase Management"
    assert inv.evaluation_status is None or inv.evaluation_status == ""


@pytest.mark.asyncio
async def test_continue_syncs_register_before_approval_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commercial docs held for match_not_clean must still sync SO/PO register first."""
    from app.services.invoice import vision_posting_continue as vpc
    from app.services.tenant.tenant_org_context import OrgContext
    from app.schemas.rule_book_config import RuleBookConfigPayload

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
        evaluation_status=EVAL_VISION_VAULTED,
        route_target="Sales Management",
        so_reference="SO-TEST-003",
        vendor="Harbour",
    )
    defn = _dt(route="Sales Management", approval_mode="touchless_on_clean_match")
    config = RuleBookConfigPayload(document_types=[defn])

    class _Session:
        async def execute(self, _stmt):
            class _R:
                def scalar_one(self_inner):
                    return inv

            return _R()

        async def flush(self):
            return None

        async def get(self, *_a, **_k):
            return None

    order: list[str] = []

    async def _noop(*_a, **_k):
        return None

    async def _noop_false(*_a, **_k):
        return False

    async def _fake_prepare(session, invoice, *, bypass_review_gates=False):
        order.append("prepare")
        invoice.sales_document_type = "invoice"
        return False

    async def _fake_approval(session, invoice, **_k):
        order.append("approval")
        assert (invoice.sales_document_type or "") == "invoice"
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = "pending_approval"
        return True

    async def _fake_resume(*_a, **_k):
        order.append("resume")
        return None

    monkeypatch.setattr(
        "app.services.invoice.pipeline._sync_counterparty_and_evaluate",
        _noop,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._vendor_hold_unless_skipped",
        _noop_false,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.prepare_route_register_before_posting",
        _fake_prepare,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.resume_invoice_posting_pipeline",
        _fake_resume,
    )
    monkeypatch.setattr(vpc, "log_event", _noop)
    async def _fake_validations(*_a, **_k):
        return []

    monkeypatch.setattr(vpc, "run_all_validations", _fake_validations)
    monkeypatch.setattr(vpc, "all_passed", lambda _r: True)
    monkeypatch.setattr(vpc, "results_to_json", lambda _r: [])
    monkeypatch.setattr(vpc, "apply_document_type_approval_gate", _fake_approval)
    monkeypatch.setattr(vpc, "send_notification", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.approval.approval_pipeline_service.human_approved_payable_bypass",
        _noop_false,
    )

    await vpc.continue_vision_understood_posting(
        _Session(),  # type: ignore[arg-type]
        inv,
        config=config,
        org=OrgContext(legal_name="Tenant"),
        definition=defn,
    )
    assert order == ["prepare", "approval"]
    assert inv.sales_document_type == "invoice"
    assert inv.evaluation_status == "pending_approval"


def test_vision_should_sync_register_for_bundle_roles() -> None:
    from app.services.invoice.vision_posting_continue import vision_should_sync_register

    grn = DocumentTypeDefinition(
        code="DT-GRN",
        title="Goods Receipt Note",
        shortTitle="GRN",
        klass="Non-transactional",
        posting="No",
        recognitionMode="signals",
        recognitionSignals=["heading_grn"],
        llmPrompt="",
        routeTarget="Purchase Management",
        playbookProfile="supporting",
        purchaseBundleRole="grn",
        enabled=True,
    )
    assert vision_should_sync_register(grn) is True

    vault = DocumentTypeDefinition(
        code="DT-AWB",
        title="Air Waybill",
        shortTitle="AWB",
        klass="Non-transactional",
        posting="No",
        recognitionMode="signals",
        recognitionSignals=["heading_transport"],
        llmPrompt="",
        routeTarget="Vault",
        playbookProfile="supporting",
        enabled=True,
    )
    assert vision_should_sync_register(vault) is False


def test_amount_inconsistent_blocks_posting_and_holds_header_review() -> None:
    from decimal import Decimal

    from app.services.invoice.invoice_evaluation_service import EVAL_VISION_HEADER_REVIEW
    from app.services.invoice.vision_posting_continue import (
        EXTRACTED_AMOUNT_INCONSISTENCY,
        vision_hold_evaluation_status,
        vision_posting_skip_reason,
        vision_posting_skip_user_message,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
        vendor="Acme",
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("999"),
    )
    defn = _dt(posting="Yes")
    assert vision_should_continue_posting(inv, defn, header_ok=True) is False
    assert vision_posting_skip_reason(inv, defn, header_ok=True) == "amount_inconsistent"
    assert vision_hold_evaluation_status(inv, defn, header_ok=True) == EVAL_VISION_HEADER_REVIEW
    assert (inv.extracted_fields or {}).get(EXTRACTED_AMOUNT_INCONSISTENCY) is True
    assert "do not add up" in vision_posting_skip_user_message(inv, defn, header_ok=True).lower()


def test_tax_inclusive_amounts_do_not_block_posting() -> None:
    from decimal import Decimal

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-07",
        vendor="Acme",
        subtotal=Decimal("120"),
        gst=Decimal("20"),
        total=Decimal("120"),
    )
    assert vision_should_continue_posting(inv, _dt(posting="Yes"), header_ok=True) is True
