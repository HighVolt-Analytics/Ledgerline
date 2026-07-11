#!/usr/bin/env python3
"""End-to-end session scenario verification — runs all 7 scenarios with evidence."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.collection import Collection
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.payment import Payment
from app.models.purchase_order import PurchaseOrder
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.dossier.dossier_pipeline_service import build_dossier_pipeline, first_pipeline_failure
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
from app.services.purchase.purchase_match_service import approve_purchase_variance
from app.services.rule_book.rule_book_config_repository import (
    fetch_config_dict,
    upgrade_tenant_coa_if_needed,
)
from app.services.signup.signup_fulfillment_service import ensure_pending_auth_account, fulfill_signup_tenant
from app.services.signup.signup_session_service import SignupSession
from app.services.tenant.tenant_setup_checklist_service import build_setup_checklist_state
from app.services.rule_book.account_mapper import coa_functional_for_journaling
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from app.workers.tasks import process_invoice_by_id

API = "http://127.0.0.1:8001"
THIN_TENANT = TESTING_TENANT_UUID
PO_NUMBER = "PO-2026-0612"
VARIANCE_INVOICE_ID = 187
BASELINE_INVOICE_ID = 184
RESULTS_PATH = Path(__file__).resolve().parent / "e2e_session_results.json"


def _ser(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "value"):
        return v.value
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


async def _auth_for_tenant(tenant_id: uuid.UUID) -> tuple[str, str]:
    async with async_session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if not tenant or not user:
            raise RuntimeError(f"No user for tenant {tenant_id}")
        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant_id,
            tenant_slug=tenant.slug,
            email=user.email,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
        )
        return token, tenant.slug


async def _api(
    method: str,
    path: str,
    *,
    token: str,
    tenant_id: uuid.UUID,
    json_body: dict | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(tenant_id),
    }
    async with httpx.AsyncClient(base_url=API, timeout=120.0) as client:
        r = await client.request(method, path, headers=headers, json=json_body)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        return {"status": r.status_code, "body": body}


async def _invoice_snapshot(session, inv_id: int) -> dict:
    inv = (
        await session.execute(
            select(Invoice).where(Invoice.id == inv_id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    if not inv:
        return {"found": False, "id": inv_id}
    jc = (
        await session.execute(
            select(func.count()).select_from(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()
    journals = (
        await session.execute(
            select(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
            .order_by(JournalEntry.id)
        )
    ).scalars().all()
    logs = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id == inv.id)
            .order_by(AuditLog.id.desc())
            .limit(30)
        )
    ).scalars().all()
    pipeline = build_dossier_pipeline(inv, list(reversed(logs)))
    fail = first_pipeline_failure(pipeline)
    match_step = next((s for s in pipeline if s.stage_id == "match"), None)
    return {
        "found": True,
        "id": inv.id,
        "tenant_id": str(inv.tenant_id),
        "invoice_no": inv.invoice_no,
        "vendor": inv.vendor,
        "status": _ser(inv.status),
        "document_type_code": inv.document_type_code,
        "po_reference": inv.po_reference,
        "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
        "subtotal": _ser(inv.subtotal),
        "gst": _ser(inv.gst),
        "total": _ser(inv.total),
        "journal_count": jc,
        "line_items": [
            {"description": (li.description or "")[:70], "qty": _ser(li.qty), "amount": _ser(li.amount)}
            for li in (inv.line_items or [])
        ],
        "journals": [
            {
                "account_code": j.account_code,
                "account_name": j.account_name,
                "debit": _ser(j.debit),
                "credit": _ser(j.credit),
                "entry_kind": getattr(j, "entry_kind", None),
                "vendor_registry_id": getattr(j, "vendor_registry_id", None),
                "customer_registry_id": getattr(j, "customer_registry_id", None),
                "payment_id": getattr(j, "payment_id", None),
            }
            for j in journals
        ],
        "dossier_first_fail": fail.stage_id if fail else None,
        "dossier_first_fail_code": fail.exception_code if fail else None,
        "dossier_match_state": match_step.state if match_step else None,
        "dossier_match_detail": match_step.detail if match_step else None,
        "audit_events": [
            {
                "id": lg.id,
                "event": lg.event,
                "created_at": lg.created_at.isoformat() if lg.created_at else None,
                "detail": lg.detail,
            }
            for lg in sorted(logs, key=lambda x: x.id)
            if lg.event
            in {
                "three_way_match_evaluated",
                "approval_required",
                "three_way_match_variance_unapproved",
                "journal_control_account_unresolved",
                "invoice_processed",
                "parse_completed",
                "ocr_completed",
                "purchase_variance_approved",
                "variance_approval_posting_resumed",
            }
        ],
    }


async def _wait_invoice(inv_id: int, *, expect_status: set[str] | None = None, timeout: int = 180) -> bool:
    for _ in range(timeout):
        async with async_session_factory() as session:
            inv = (await session.execute(select(Invoice.status).where(Invoice.id == inv_id))).scalar_one_or_none()
            if inv is None:
                return False
            st = inv.value if hasattr(inv, "value") else str(inv)
            if expect_status and st in expect_status:
                return True
            if not expect_status and st not in {
                InvoiceStatus.PENDING.value,
                InvoiceStatus.PARSING.value,
                InvoiceStatus.MAPPING.value,
                InvoiceStatus.JOURNALING.value,
                InvoiceStatus.RECONCILING.value,
            }:
                return True
        await asyncio.sleep(1)
    return False


async def _provision_fresh_tenant(label: str) -> tuple[uuid.UUID, str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"e2e-{label}-{suffix}@example.com"
    async with async_session_factory() as session:
        account = await ensure_pending_auth_account(session, email=email, password_hash=hash_password("E2eTest123!"))
        signup = SignupSession(
            session_id=f"e2e-{suffix}",
            email=email,
            full_name=f"E2E {label}",
            provider="email",
            status="provisioning",
            organization_name=f"E2E {label} {suffix}",
            organization_slug=f"e2e-{label}-{suffix}",
            country="AU",
            plan="free",
            password_hash=account.password_hash,
            auth_account_id=account.id,
        )
        tenant, user = await fulfill_signup_tenant(session, signup=signup)
        await session.commit()
        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            email=user.email,
            role=user.role.value,
        )
        return tenant.id, tenant.slug, token


async def _prepare_test_tenant() -> dict[str, Any]:
    """Snapshot pre-upgrade COA, then merge starter accounts for E2E journaling."""
    async with async_session_factory() as session:
        raw = await fetch_config_dict(session, THIN_TENANT)
        pre_cfg = validate_rule_book_config_payload(raw or {})
        pre = {
            "coa_count": len(pre_cfg.chart_of_accounts),
            "coa_functional": coa_functional_for_journaling(pre_cfg),
            "coa": [{"code": a.code, "name": a.name} for a in pre_cfg.chart_of_accounts],
        }
        upgraded = await upgrade_tenant_coa_if_needed(session, THIN_TENANT)
        await session.commit()
        raw_after = await fetch_config_dict(session, THIN_TENANT)
        post_cfg = validate_rule_book_config_payload(raw_after or {})
        return {
            "upgraded": upgraded,
            "pre_upgrade": pre,
            "post_upgrade_coa_count": len(post_cfg.chart_of_accounts),
            "post_upgrade_functional": coa_functional_for_journaling(post_cfg),
        }


async def scenario_1_baseline(report: dict) -> None:
    """Clean three-way match baseline on invoice 184 after COA upgrade."""
    out: dict[str, Any] = {"name": "Scenario 1 — Clean three-way match baseline"}
    token, _ = await _auth_for_tenant(THIN_TENANT)

    async with async_session_factory() as session:
        snap = await _invoice_snapshot(session, BASELINE_INVOICE_ID)
        out["invoice_184"] = snap

        match_log = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == BASELINE_INVOICE_ID,
                    AuditLog.event == "three_way_match_evaluated",
                )
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if match_log and isinstance(match_log.detail, dict):
            out["match_eval"] = {
                k: match_log.detail.get(k)
                for k in ["match_status", "qty_variance_value", "po_number"]
            }

    out["api_journal_entries"] = await _api(
        "GET", f"/api/invoices/{BASELINE_INVOICE_ID}/journal-entries", token=token, tenant_id=THIN_TENANT
    )

    ap_credit = [
        j
        for j in snap.get("journals", [])
        if j.get("credit") not in (None, "0.00", "0", 0)
        and "payable" in (j.get("account_name") or "").lower()
    ]
    out["checks"] = {
        "status_processed": snap.get("status") == "processed",
        "match_status_3way": out.get("match_eval", {}).get("match_status") == "3-Way Match",
        "journals_present": snap.get("journal_count", 0) >= 1,
        "vendor_registry_on_ap_credit": any(j.get("vendor_registry_id") for j in ap_credit),
        "api_journals_200": out["api_journal_entries"].get("status") == 200,
    }
    out["pass"] = (
        out["checks"]["status_processed"]
        and out["checks"]["match_status_3way"]
        and out["checks"]["journals_present"]
        and out["checks"]["api_journals_200"]
    )
    report["scenario_1"] = out


async def scenario_2_variance(report: dict) -> None:
    out: dict[str, Any] = {"name": "Scenario 2 — Quantity variance PO-2026-0612 / invoice 187"}

    async with async_session_factory() as session:
        snap = await _invoice_snapshot(session, VARIANCE_INVOICE_ID)
        out["invoice_187"] = snap

        hold = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == VARIANCE_INVOICE_ID,
                    AuditLog.event == "three_way_match_variance_unapproved",
                )
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out["variance_hold_audit"] = (
            {"id": hold.id, "event": hold.event, "detail": hold.detail} if hold else None
        )

        resume_events = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == VARIANCE_INVOICE_ID,
                    AuditLog.event.in_(
                        [
                            "variance_approval_posting_resumed",
                            "ocr_completed",
                            "parse_completed",
                            "invoice_processed",
                        ]
                    ),
                )
                .order_by(AuditLog.id.desc())
                .limit(10)
            )
        ).scalars().all()
        out["recent_resume_audits"] = [
            {"id": lg.id, "event": lg.event, "created_at": lg.created_at.isoformat() if lg.created_at else None}
            for lg in resume_events
        ]

        token, _ = await _auth_for_tenant(THIN_TENANT)
        out["api_journals"] = await _api(
            "GET", f"/api/invoices/{VARIANCE_INVOICE_ID}/journal-entries", token=token, tenant_id=THIN_TENANT
        )

    resume_ids = [e["id"] for e in out["recent_resume_audits"] if e["event"] == "variance_approval_posting_resumed"]
    max_resume_id = max(resume_ids) if resume_ids else 0
    ocr_after_resume = sum(
        1
        for e in out["recent_resume_audits"]
        if e["event"] == "ocr_completed" and e["id"] > max_resume_id
    )
    parse_after_resume = sum(
        1
        for e in out["recent_resume_audits"]
        if e["event"] == "parse_completed" and e["id"] > max_resume_id
    )
    match_detail = (out.get("variance_hold_audit") or {}).get("detail") or {}

    snap = out["invoice_187"]
    out["checks"] = {
        "variance_hold_in_audit_trail": out["variance_hold_audit"] is not None,
        "match_status_qty_variance": match_detail.get("match_status") == "Qty Variance",
        "qty_variance_positive": (match_detail.get("qty_variance_value") or 0) > 0,
        "dossier_match_fail": snap.get("dossier_match_state") == "fail"
        if snap.get("status") == "exception"
        else snap.get("status") == "processed",
        "post_approve_processed": snap.get("status") == "processed",
        "post_approve_journals": snap.get("journal_count", 0) >= 1,
        "no_ocr_after_last_resume": ocr_after_resume == 0,
        "no_parse_after_last_resume": parse_after_resume == 0,
        "full_loop_script": "scripts/verify_variance_gate_187.py (run separately for live reprocess loop)",
    }
    out["pass"] = (
        out["checks"]["variance_hold_in_audit_trail"]
        and out["checks"]["match_status_qty_variance"]
        and out["checks"]["qty_variance_positive"]
        and out["checks"]["post_approve_processed"]
        and out["checks"]["post_approve_journals"]
        and out["checks"]["no_ocr_after_last_resume"]
        and out["checks"]["no_parse_after_last_resume"]
    )
    report["scenario_2"] = out


async def scenario_3_thin_coa(report: dict, *, tenant_prep: dict[str, Any]) -> None:
    out: dict[str, Any] = {"name": "Scenario 3 — Sales invoice thin vs seeded COA"}
    out["pre_upgrade_tenant"] = tenant_prep.get("pre_upgrade")
    out["post_upgrade"] = {
        "coa_count": tenant_prep.get("post_upgrade_coa_count"),
        "functional": tenant_prep.get("post_upgrade_functional"),
    }

    async with async_session_factory() as session:
        ctrl = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == VARIANCE_INVOICE_ID,
                    AuditLog.event == "journal_control_account_unresolved",
                )
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out["historical_control_gate_187"] = (
            {"id": ctrl.id, "detail": ctrl.detail} if ctrl else None
        )

    fresh_id, fresh_slug, _fresh_token = await _provision_fresh_tenant("coa-contrast")
    out["fresh_tenant"] = {"id": str(fresh_id), "slug": fresh_slug}
    async with async_session_factory() as session:
        raw = await fetch_config_dict(session, fresh_id)
        cfg = validate_rule_book_config_payload(raw)
        out["fresh_tenant_coa"] = [{"code": a.code, "name": a.name} for a in cfg.chart_of_accounts]
        out["fresh_tenant_posting_defaults"] = cfg.posting_defaults.model_dump()

    pre = tenant_prep.get("pre_upgrade") or {}
    out["checks"] = {
        "pre_upgrade_coa_thin": pre.get("coa_count", 0) < 8,
        "pre_upgrade_not_functional": pre.get("coa_functional") is False,
        "post_upgrade_functional": tenant_prep.get("post_upgrade_functional") is True,
        "historical_control_gate_logged": out["historical_control_gate_187"] is not None,
        "fresh_tenant_has_8_accounts": len(out["fresh_tenant_coa"]) >= 8,
        "fresh_has_receivable": any("receivable" in a["name"].lower() for a in out["fresh_tenant_coa"]),
    }
    out["pass"] = (
        out["checks"]["post_upgrade_functional"]
        and out["checks"]["fresh_tenant_has_8_accounts"]
        and out["checks"]["fresh_has_receivable"]
        and (
            out["checks"]["pre_upgrade_not_functional"]
            or out["checks"]["historical_control_gate_logged"]
        )
    )
    report["scenario_3"] = out


async def scenario_4_unmatched(report: dict) -> None:
    out: dict[str, Any] = {"name": "Scenario 4 — Invoice-only unmatched approval routing"}

    candidate_ids = [251, 199, 227]
    chosen: dict[str, Any] | None = None
    async with async_session_factory() as session:
        for iid in candidate_ids:
            snap = await _invoice_snapshot(session, iid)
            if snap.get("po_reference") is not None:
                continue
            if snap.get("status") != "processed":
                continue
            holds = (
                await session.execute(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.invoice_id == iid, AuditLog.event == "approval_required")
                )
            ).scalar()
            snap["approval_required_count"] = holds
            if holds == 0:
                chosen = {"invoice_id": iid, **snap}
                break
            if chosen is None:
                chosen = {"invoice_id": iid, **snap}

    out["candidate"] = chosen
    snap = chosen or {}
    out["checks"] = {
        "candidate_found": chosen is not None,
        "no_po_reference": snap.get("po_reference") is None,
        "status_processed": snap.get("status") == "processed",
        "no_approval_required_holds": (snap.get("approval_required_count") or 0) == 0,
        "opt_in_unmatched_note": (
            "require_approval_for_unmatched live toggle verified in test_approval_risk_routing.py"
        ),
    }
    out["pass"] = (
        out["checks"]["candidate_found"]
        and out["checks"]["no_po_reference"]
        and out["checks"]["status_processed"]
        and out["checks"]["no_approval_required_holds"]
    )
    report["scenario_4"] = out


async def scenario_5_packing_list(report: dict) -> None:
    out: dict[str, Any] = {"name": "Scenario 5 — Packing list invoice 262 extraction"}

    async with async_session_factory() as session:
        raw = await fetch_config_dict(session, THIN_TENANT)
        cfg = validate_rule_book_config_payload(raw or {})
        dt13 = next((d for d in cfg.document_types if (d.code or "").upper() == "DT-13"), None)
        out["dt13_extraction_fields"] = list(dt13.extraction_fields) if dt13 else []

    async with async_session_factory() as session:
        snap = await _invoice_snapshot(session, 262)
        out["invoice_262"] = snap

        parse_logs = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.invoice_id == 262, AuditLog.event == "parse_completed")
                .order_by(AuditLog.id.desc())
                .limit(3)
            )
        ).scalars().all()
        out["parse_completed_audits"] = [
            {"id": lg.id, "detail": lg.detail, "created_at": lg.created_at.isoformat() if lg.created_at else None}
            for lg in parse_logs
        ]

    line_count = len(snap.get("line_items", []))
    descriptions = [li.get("description", "") for li in snap.get("line_items", [])]
    cpu_lines = [d for d in descriptions if "CPU CHIPS" in d.upper()]
    garbage = [d for d in descriptions if any(x in d.upper() for x in ["DOCUMENTARY", "ADDRESS", "MODEL NUMBER", "PROFORMA"])]

    out["checks"] = {
        "invoice_no_is_260371344_not_proforma": snap.get("invoice_no") == "260371344",
        "vendor_is_walton_not_spectra": "WALTON" in (snap.get("vendor") or "").upper(),
        "line_item_count_five": line_count == 5,
        "all_lines_cpu_chips": len(cpu_lines) == line_count and line_count == 5,
        "no_garbage_lines": len(garbage) == 0,
        "invoice_date_in_dt13_config": "invoice_date" in [f.lower() for f in out.get("dt13_extraction_fields", [])],
        "invoice_date_populated": snap.get("invoice_date") is not None,
    }
    out["pass"] = (
        out["checks"]["invoice_no_is_260371344_not_proforma"]
        and out["checks"]["vendor_is_walton_not_spectra"]
        and out["checks"]["line_item_count_five"]
        and out["checks"]["no_garbage_lines"]
        and out["checks"]["invoice_date_in_dt13_config"]
    )
    report["scenario_5"] = out


async def scenario_6_settlement(report: dict) -> None:
    out: dict[str, Any] = {"name": "Scenario 6 — Payment settlement + subledger balance"}
    token, _ = await _auth_for_tenant(THIN_TENANT)

    async with async_session_factory() as session:
        payment = (
            await session.execute(
                select(Payment)
                .where(Payment.invoice_id == BASELINE_INVOICE_ID)
                .order_by(Payment.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not payment:
            payment = (
                await session.execute(
                    select(Payment).where(Payment.tenant_id == THIN_TENANT).order_by(Payment.id.desc()).limit(1)
                )
            ).scalar_one_or_none()
        out["payment_used"] = (
            {"id": payment.id, "invoice_id": payment.invoice_id, "amount": _ser(payment.amount), "status": _ser(payment.status)}
            if payment
            else None
        )

    if not payment:
        out["error"] = "No payment row found for settlement test"
        out["pass"] = False
        report["scenario_6"] = out
        return

    async with async_session_factory() as session:
        before_jc = (
            await session.execute(
                select(func.count())
                .select_from(JournalEntry)
                .where(
                    JournalEntry.tenant_id == THIN_TENANT,
                    JournalEntry.payment_id == payment.id,
                    JournalEntry.entry_kind == "payment_settlement",
                )
            )
        ).scalar()

    api_instruction = await _api(
        "POST",
        f"/api/payments/{payment.id}/execution-instruction",
        token=token,
        tenant_id=THIN_TENANT,
    )
    out["create_instruction"] = api_instruction

    api_mark1 = await _api(
        "POST",
        f"/api/payments/{payment.id}/mark-paid-manual",
        token=token,
        tenant_id=THIN_TENANT,
        json_body={
            "reference": "E2E-SETTLE-001",
            "paid_date": str(date.today()),
            "proof_reference": "e2e-test",
            "note": "E2E settlement scenario 6",
        },
    )
    out["mark_paid_first"] = api_mark1

    async with async_session_factory() as session:
        settlement_journals = (
            await session.execute(
                select(JournalEntry)
                .where(
                    JournalEntry.tenant_id == THIN_TENANT,
                    JournalEntry.payment_id == payment.id,
                    JournalEntry.entry_kind == "payment_settlement",
                )
                .order_by(JournalEntry.id)
            )
        ).scalars().all()
        out["settlement_journals"] = [
            {
                "account_name": j.account_name,
                "debit": _ser(j.debit),
                "credit": _ser(j.credit),
                "entry_kind": j.entry_kind,
                "payment_id": j.payment_id,
                "vendor_registry_id": getattr(j, "vendor_registry_id", None),
            }
            for j in settlement_journals
        ]

    api_mark2 = await _api(
        "POST",
        f"/api/payments/{payment.id}/mark-paid-manual",
        token=token,
        tenant_id=THIN_TENANT,
        json_body={
            "reference": "E2E-SETTLE-001-DUP",
            "paid_date": str(date.today()),
            "proof_reference": "e2e-test-dup",
        },
    )
    out["mark_paid_second_idempotent"] = api_mark2

    ap_balances = await _api("GET", "/api/reports/subledger/ap-balances?limit=50", token=token, tenant_id=THIN_TENANT)
    out["ap_balances"] = ap_balances

    # AR collection leg
    async with async_session_factory() as session:
        coll = (
            await session.execute(
                select(Collection)
                .where(Collection.tenant_id == THIN_TENANT)
                .order_by(Collection.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out["collection_used"] = {"id": coll.id, "invoice_id": coll.invoice_id} if coll else None

    if coll:
        coll_api = await _api(
            "POST",
            f"/api/collections/{coll.id}/mark-received",
            token=token,
            tenant_id=THIN_TENANT,
            json_body={"note": "E2E scenario 6 AR"},
        )
        out["mark_collection_received"] = coll_api
        ar_balances = await _api(
            "GET", "/api/reports/subledger/ar-balances?limit=50", token=token, tenant_id=THIN_TENANT
        )
        out["ar_balances"] = ar_balances

    after_jc = len(out.get("settlement_journals", []))
    out["checks"] = {
        "settlement_journal_created": after_jc >= 1,
        "idempotent_second_call": api_mark2.get("body", {}).get("data", {}).get("changed") is False
        if isinstance(api_mark2.get("body"), dict)
        else "check response",
        "ap_balances_200": ap_balances.get("status") == 200,
        "settlement_has_vendor_registry": any(j.get("vendor_registry_id") for j in out.get("settlement_journals", [])),
    }
    out["pass"] = out["checks"]["settlement_journal_created"] and out["checks"]["ap_balances_200"]
    report["scenario_6"] = out


async def scenario_7_new_tenant(report: dict) -> None:
    out: dict[str, Any] = {"name": "Scenario 7 — New tenant HTTP signup path"}
    suffix = uuid.uuid4().hex[:8]
    email = f"e2e-signup-{suffix}@example.com"
    password = "E2eSignup123!"

    async with httpx.AsyncClient(base_url=API, timeout=120.0) as client:
        reg = await client.post(
            "/api/signup/register",
            json={"email": email, "password": password, "full_name": f"E2E Signup {suffix}"},
        )
        out["register"] = {"status": reg.status_code, "body": reg.json() if reg.status_code < 500 else reg.text}

        ch = reg.json()["data"]["challenge_token"]
        verify = await client.post(
            "/api/signup/verify-otp",
            json={"otp": "123456"},
            headers={"Authorization": f"Bearer {ch}"},
        )
        out["verify_otp"] = {"status": verify.status_code}
        signup_token = verify.json()["data"]["signup_token"]

        org = await client.post(
            "/api/signup/organization",
            json={"organization_name": f"E2E Org {suffix}", "country": "AU"},
            headers={"Authorization": f"Bearer {signup_token}"},
        )
        out["organization"] = {"status": org.status_code}

        plan = await client.post(
            "/api/signup/select-plan",
            json={"plan": "free"},
            headers={"Authorization": f"Bearer {signup_token}"},
        )
        out["select_plan"] = {"status": plan.status_code}

        complete = await client.post(
            "/api/signup/complete-free",
            headers={"Authorization": f"Bearer {signup_token}"},
        )
        out["complete_free"] = {"status": complete.status_code}
        complete_body = complete.json()
        access_token = complete_body["data"]["access_token"]
        tenant_id = uuid.UUID(complete_body["data"]["user"]["tenant_id"])

    async with async_session_factory() as session:
        raw = await fetch_config_dict(session, tenant_id)
        cfg = validate_rule_book_config_payload(raw)
        out["provisioned_coa"] = [{"code": a.code, "name": a.name} for a in cfg.chart_of_accounts]
        out["posting_defaults"] = cfg.posting_defaults.model_dump()
        tenant = await session.get(Tenant, tenant_id)
        user = (
            await session.execute(select(User).where(User.tenant_id == tenant_id).limit(1))
        ).scalar_one_or_none()
        checklist = await build_setup_checklist_state(
            session,
            tenant=tenant,
            user_role=user.role.value if user else "admin",
            is_support_session=False,
        )
        out["setup_checklist"] = [
            {"id": i.id, "label": i.label, "done": i.done} for i in checklist.items
        ]

    coa_item = next((i for i in out["setup_checklist"] if i["id"] == "chart_of_accounts"), None)
    out["checks"] = {
        "signup_http_200": out["complete_free"]["status"] == 200,
        "coa_seeded_8_accounts": len(out["provisioned_coa"]) >= 8,
        "has_payable_and_receivable": any("payable" in a["name"].lower() for a in out["provisioned_coa"])
        and any("receivable" in a["name"].lower() for a in out["provisioned_coa"]),
        "checklist_coa_complete": coa_item["done"] if coa_item else False,
        "upload_invoices": "Not run — no sample PDFs wired in this script; COA provisioning verified via HTTP signup.",
    }
    out["pass"] = (
        out["checks"]["signup_http_200"]
        and out["checks"]["coa_seeded_8_accounts"]
        and out["checks"]["has_payable_and_receivable"]
        and out["checks"]["checklist_coa_complete"]
    )
    report["scenario_7"] = out


async def main() -> None:
    report: dict[str, Any] = {"run_at": date.today().isoformat(), "api_base": API}
    report["tenant_prep"] = await _prepare_test_tenant()
    await scenario_1_baseline(report)
    await scenario_2_variance(report)
    await scenario_3_thin_coa(report, tenant_prep=report["tenant_prep"])
    await scenario_4_unmatched(report)
    await scenario_5_packing_list(report)
    await scenario_6_settlement(report)
    await scenario_7_new_tenant(report)

    summary = {k: v.get("pass") for k, v in report.items() if k.startswith("scenario_")}
    report["summary"] = summary
    payload = json.dumps(report, indent=2, default=str)
    print(payload)
    RESULTS_PATH.write_text(payload, encoding="utf-8")
    if not all(summary.values()):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
