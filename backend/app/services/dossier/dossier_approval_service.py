"""Build dossier approval chain from document-type policy + audit trail."""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import DossierApprovalChainResponse, DossierApprovalStepResponse
from app.services.classification.document_type_approval_service import has_document_approval
from app.services.classification.document_type_playbook_profile_service import effective_approval_policy
from app.services.invoice.pipeline_stages import _actor_name, _latest_log
from sqlalchemy.ext.asyncio import AsyncSession

_APPROVAL_LABELS = {
    "no_posting": "No posting",
    "touchless_on_clean_match": "Touchless when matched",
    "full_doa": "Full DOA approval",
    "supervisor_on_exception": "Supervisor on exception",
    "never_touchless": "Never touchless",
    "manager_gate": "Manager gate (team expenses)",
    "variance_workflow": "Variance workflow",
}

# Vision understood path ends at vault — no DOA / Approvals / ledger / payment.
_UNDERSTOOD_POLICY_MODE = "no_posting"
_UNDERSTOOD_POLICY_LABEL = "Understood path — vault only"

_DETAIL_HUMAN: dict[str, str] = {
    "invoice_approved": "Approved in Approvals",
    "approval_required": "Waiting for approver",
    "approval_required cleared": "Approval gate cleared",
    "team_expense_approval_required": "Waiting for manager approval",
    "Opens in /approvals when required": "Will appear in Approvals if needed",
}

_POLICY_REF_HUMAN: dict[str, str | None] = {
    "DOA-01": "Buyer authority",
    "PAY-tier": "Payment tier",
    "Post": None,
    "invoice_approved": None,
    "touchless_on_clean_match": None,
    "full_doa": "Full DOA",
    "supervisor_on_exception": "Supervisor gate",
    "never_touchless": "Always manual",
    "manager_gate": "Manager gate",
    "variance_workflow": "Variance policy",
    "no_posting": None,
}


def _human_detail(text: str | None) -> str | None:
    if not text:
        return None
    token = text.strip()
    if not token:
        return None
    if token in _DETAIL_HUMAN:
        return _DETAIL_HUMAN[token]
    lowered = token.lower()
    if lowered == "invoice_approved":
        return _DETAIL_HUMAN["invoice_approved"]
    if "approval_required" in lowered and "cleared" in lowered:
        return _DETAIL_HUMAN["approval_required cleared"]
    return token


def _human_policy_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    token = ref.strip()
    if not token:
        return None
    mapped = _POLICY_REF_HUMAN.get(token)
    if mapped is None and token in _POLICY_REF_HUMAN:
        return None
    if mapped:
        return mapped
    if token in _APPROVAL_LABELS:
        return None
    if "_" in token and token == token.lower():
        return None
    return token


def _fmt_at(log: AuditLog | None) -> str | None:
    if log is None:
        return None
    return log.created_at.strftime("%Y-%m-%d %H:%M:%S")


def _step(
    *,
    step_id: str,
    kind: str,
    label: str,
    role: str,
    actor: str,
    state: str,
    at: str | None = None,
    detail: str | None = None,
    policy_ref: str | None = None,
    sod_note: str | None = None,
) -> DossierApprovalStepResponse:
    return DossierApprovalStepResponse(
        id=step_id,
        kind=kind,
        label=label,
        role=role,
        actor=actor,
        state=state,
        at=at,
        detail=_human_detail(detail),
        policy_ref=_human_policy_ref(policy_ref),
        sod_note=sod_note,
    )


def build_understood_dossier_approval_chain() -> DossierApprovalChainResponse:
    """Approval rail for vault-only vision-understood docs (no post/pay gates)."""
    not_on_path = "Not on vault-only understood path — document stops at vault"
    return DossierApprovalChainResponse(
        policy_mode=_UNDERSTOOD_POLICY_MODE,
        policy_label=_UNDERSTOOD_POLICY_LABEL,
        steps=[
            _step(
                step_id="document_gate",
                kind="document_gate",
                label="Document-type approval gate",
                role="Approver",
                actor="—",
                state="not_required",
                detail=not_on_path,
            ),
            _step(
                step_id="exception_queue",
                kind="exception_queue",
                label="Exception queue approval",
                role="Approver",
                actor="—",
                state="not_required",
                detail="Does not appear in Approvals on this path",
            ),
            _step(
                step_id="publish",
                kind="publish",
                label="Post to ledger",
                role="Post",
                actor="—",
                state="not_required",
                detail="Vault storage only — not posted to the ledger",
            ),
            _step(
                step_id="payment",
                kind="payment",
                label="Payment disbursement",
                role="Approver",
                actor="—",
                state="not_required",
                detail="Payment not applicable on understood path",
            ),
        ],
    )


async def build_dossier_approval_chain(
    session: AsyncSession,
    invoice: Invoice,
    logs: list[AuditLog],
    *,
    definition: DocumentTypeDefinition | None,
    payment: Payment | None,
    published: bool,
    pipeline_path: str | None = None,
) -> DossierApprovalChainResponse:
    from app.services.invoice.pipeline_stages import vision_posting_continues

    if (pipeline_path or "").strip().lower() == "understood" and not vision_posting_continues(logs):
        return build_understood_dossier_approval_chain()

    mode = effective_approval_policy(definition).mode if definition else "touchless_on_clean_match"
    from app.services.classification.document_type_catalog import (
        ROUTE_TEAM,
        is_team_expenses_document_type,
    )

    route = (invoice.route_target or "").strip()
    if mode != "manager_gate" and (
        route == ROUTE_TEAM or is_team_expenses_document_type(definition)
    ):
        mode = "manager_gate"
    policy_label = _APPROVAL_LABELS.get(mode, mode.replace("_", " ").title())

    approved_log = _latest_log(logs, "invoice_approved")
    approval_required = _latest_log(logs, "approval_required")
    team_expense_approval = _latest_log(logs, "team_expense_approval_required")
    # Manager gate (Team Expenses) uses team_expense_approval_required, not approval_required.
    gate_required = approval_required or (
        team_expense_approval if mode == "manager_gate" or route == ROUTE_TEAM else None
    )
    variance_log = _latest_log(logs, "purchase_variance_approved")
    published_log = _latest_log(logs, "invoice_published_to_ledger")

    approved = approved_log is not None or await has_document_approval(session, invoice.id)
    approved_actor = _actor_name(approved_log.detail if approved_log else None) or "—"

    steps: list[DossierApprovalStepResponse] = []

    if mode in {"touchless_on_clean_match", "variance_workflow", "supervisor_on_exception"}:
        po_waived = approved or invoice.status == InvoiceStatus.PROCESSED
        steps.append(
            _step(
                step_id="po_buyer",
                kind="po_buyer",
                label="PO buyer authorization",
                role="Buyer",
                actor="Policy engine" if po_waived else "—",
                state="waived" if po_waived else "pending",
                detail="PO approval on file satisfies DOA" if po_waived else None,
                policy_ref="DOA-01",
            )
        )

    if mode == "variance_workflow" and not variance_log and invoice.status == InvoiceStatus.EXCEPTION:
        steps.append(
            _step(
                step_id="variance",
                kind="variance",
                label="Purchase variance approval",
                role="Buyer",
                actor="—",
                state="pending",
                detail=str((approval_required.detail or {}).get("reason", "")) if approval_required else "Variance pending",
                policy_ref="variance_workflow",
            )
        )

    gate_state = "waived"
    gate_actor = "Policy engine"
    gate_detail: str | None = "Clean match — no manual approval needed"
    gate_label = "Document-type approval gate"
    gate_policy_ref = "Playbook policy"
    if mode == "manager_gate":
        gate_label = "Manager gate (team expenses)"
        gate_policy_ref = "manager_gate"
        gate_detail = "Below auto-approve threshold — manager not required"
    if gate_required and not approved:
        gate_state = "pending"
        gate_actor = "—"
        detail = gate_required.detail if isinstance(gate_required.detail, dict) else {}
        if gate_required.event == "team_expense_approval_required":
            gate_detail = (
                str(detail.get("reason", "")).strip()
                or "Waiting for manager approval"
            )
        else:
            gate_detail = str(detail.get("reason", "")).strip() or "Waiting for approver"
    elif approved:
        gate_state = "done"
        gate_actor = approved_actor
        gate_detail = (
            f"Approved by {approved_actor}"
            if approved_actor and approved_actor != "—"
            else "Approved"
        )

    if mode not in {"no_posting"}:
        steps.append(
            _step(
                step_id="document_gate",
                kind="document_gate",
                label=gate_label,
                role="Manager" if mode == "manager_gate" else "Approver",
                actor=gate_actor,
                state=gate_state,
                at=_fmt_at(approved_log),
                detail=gate_detail,
                policy_ref=gate_policy_ref,
            )
        )

    queue_state = "waived"
    queue_actor = "System"
    if approved:
        queue_state = "done"
        queue_actor = approved_actor
    elif gate_required:
        queue_state = "pending"
        queue_actor = "—"

    steps.append(
        _step(
            step_id="exception_queue",
            kind="exception_queue",
            label="Exception queue approval",
            role="Approver",
            actor=queue_actor,
            state=queue_state,
            at=_fmt_at(approved_log),
            detail="Approved in Approvals" if approved else "Will appear in Approvals if needed",
            policy_ref=None,
        )
    )

    publish_state = "done" if published else "pending"
    publish_actor = "System" if published else "—"
    steps.append(
        _step(
            step_id="publish",
            kind="publish",
            label="Post to ledger",
            role="Post",
            actor=publish_actor,
            state=publish_state,
            at=_fmt_at(published_log),
            detail="Posted to general ledger" if published else "Waiting to post",
            policy_ref=None,
        )
    )

    pay_state = "not_required"
    pay_actor = "—"
    pay_detail: str | None = None
    sod_note: str | None = None
    if payment is not None:
        if payment.status == PaymentStatus.PAID:
            pay_state = "done"
            pay_actor = "Payments queue"
            pay_detail = "Paid"
        elif payment.status == PaymentStatus.FAILED:
            pay_state = "fail"
            pay_detail = "Payment failed"
        elif payment.status in (PaymentStatus.AWAITING, PaymentStatus.QUEUE, PaymentStatus.SCHEDULED):
            pay_state = "pending"
            pay_detail = "Awaiting payment approval"
            if payment.invoice_approved_by:
                sod_note = (
                    "Segregation of duties: invoice approver cannot release payment — "
                    "another authorised approver required."
                )
    elif invoice.status == InvoiceStatus.PROCESSED:
        pay_state = "pending"
        pay_detail = "Payment not yet queued"

    steps.append(
        _step(
            step_id="payment",
            kind="payment",
            label="Payment disbursement",
            role="Approver",
            actor=pay_actor,
            state=pay_state,
            detail=pay_detail,
            policy_ref="PAY-tier",
            sod_note=sod_note,
        )
    )

    return DossierApprovalChainResponse(
        policy_mode=mode,
        policy_label=policy_label,
        steps=steps,
    )
