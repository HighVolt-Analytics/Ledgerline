"""Build dossier approval chain from document-type policy + audit trail."""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import DossierApprovalChainResponse, DossierApprovalStepResponse
from app.services.document_type_approval_service import has_document_approval
from app.services.document_type_playbook_profile_service import effective_approval_policy
from app.services.pipeline_stages import _actor_name, _latest_log
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
        detail=detail,
        policy_ref=policy_ref,
        sod_note=sod_note,
    )


async def build_dossier_approval_chain(
    session: AsyncSession,
    invoice: Invoice,
    logs: list[AuditLog],
    *,
    definition: DocumentTypeDefinition | None,
    payment: Payment | None,
    published: bool,
) -> DossierApprovalChainResponse:
    mode = effective_approval_policy(definition).mode if definition else "touchless_on_clean_match"
    policy_label = _APPROVAL_LABELS.get(mode, mode.replace("_", " ").title())

    approved_log = _latest_log(logs, "invoice_approved")
    approval_required = _latest_log(logs, "approval_required")
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
    gate_detail: str | None = "Clean match — touchless policy"
    if approval_required and not approved:
        gate_state = "pending"
        gate_actor = "—"
        detail = approval_required.detail if isinstance(approval_required.detail, dict) else {}
        gate_detail = str(detail.get("reason", "")).strip() or "approval_required"
    elif approved:
        gate_state = "done"
        gate_actor = approved_actor
        gate_detail = "approval_required cleared"

    if mode not in {"no_posting"}:
        steps.append(
            _step(
                step_id="document_gate",
                kind="document_gate",
                label="Document-type approval gate",
                role="Approver",
                actor=gate_actor,
                state=gate_state,
                at=_fmt_at(approved_log),
                detail=gate_detail,
                policy_ref=mode,
            )
        )

    queue_state = "waived"
    queue_actor = "System"
    if approved:
        queue_state = "done"
        queue_actor = approved_actor
    elif approval_required:
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
            detail="invoice_approved" if approved else "Opens in /approvals when required",
            policy_ref="invoice_approved",
        )
    )

    publish_state = "done" if published else "pending"
    publish_actor = "System" if published else "—"
    steps.append(
        _step(
            step_id="publish",
            kind="publish",
            label="Publish to ledger",
            role="Publish",
            actor=publish_actor,
            state=publish_state,
            at=_fmt_at(published_log),
            policy_ref="Publish",
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
