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
        due_date=date(2026, 6, 1),
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
    assert vision_header_ok_from_invoice(needs_review, defn) is False


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
