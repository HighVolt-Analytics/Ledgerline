"""Vendor/employee master self-confirmation via secure email links."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.models.master_confirmation_token import MasterConfirmationToken
from app.models.tenant import Tenant
from app.models.vendor_master import VendorMasterRecord
from app.schemas.master_data import EmployeeMasterUpdate, VendorMasterUpdate
from app.schemas.rule_book_config import BankDetails, BillingAddress
from app.services.audit.audit_service import log_event
from app.services.auth.auth_email_service import InviteEmailResult, send_master_confirmation_email
from app.services.master_data.master_data_service import (
    get_employee_master_by_email,
    get_employee_master_by_id,
    get_vendor_master_by_id,
    update_employee_master,
    update_vendor_master,
)
from app.services.shared.public_app_url import build_public_app_path
from app.tenant_rls import apply_platform_lookup_session, apply_rls_session_context, clear_platform_lookup_session

MasterKind = Literal["vendor", "employee"]
TOKEN_TTL_DAYS = 7

EMPLOYEE_CONFIRM_FIELDS = frozenset(
    {
        "name",
        "email",
        "whatsapp_number",
        "whatsapp_number_2",
        "viber_number",
        "date_of_joining",
        "department",
        "role",
        "location",
        "division",
        "supervisor_1",
        "supervisor_2",
        "bank",
    }
)

VENDOR_CONFIRM_FIELDS = frozenset(
    {
        "name",
        "aliases",
        "abn",
        "billing_address",
        "bank",
        "payment_terms",
        "contact_email",
    }
)

EMPLOYEE_PENDING_STATUS = "Pending verification"
VENDOR_PENDING_STATUS = "Pending registration"
EMPLOYEE_ACTIVE_STATUS = "Active"
VENDOR_ACTIVE_STATUS = "Active"


@dataclass(frozen=True)
class ConfirmationSendResult:
    sent: bool
    email: str | None = None
    error: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ConfirmationPreview:
    kind: MasterKind
    master_id: str
    party_name: str
    tenant_name: str
    expired: bool
    confirmed: bool
    fields: dict[str, Any]


@dataclass(frozen=True)
class ConfirmationSaveResult:
    kind: MasterKind
    master_id: str
    party_name: str
    status: str
    confirmed_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _confirm_url(token: str) -> str:
    return build_public_app_path(f"/confirm-master?token={token}")


def _mask_account(account_number: str) -> str:
    digits = (account_number or "").strip()
    if len(digits) <= 4:
        return digits
    return f"****{digits[-4:]}"


def _employee_recipient(row: EmployeeMasterRecord) -> str:
    return (row.email or "").strip().lower()


def _vendor_recipient(row: VendorMasterRecord) -> str:
    return (row.contact_email or "").strip().lower()


def employee_confirmable_patch_keys(patch: dict[str, Any]) -> set[str]:
    return {key for key in patch if key in EMPLOYEE_CONFIRM_FIELDS}


def vendor_confirmable_patch_keys(patch: dict[str, Any]) -> set[str]:
    return {key for key in patch if key in VENDOR_CONFIRM_FIELDS}


def employee_fields_for_public(row: EmployeeMasterRecord) -> dict[str, Any]:
    bank = row.bank or {}
    return {
        "name": row.name or "",
        "email": row.email or "",
        "whatsapp_number": row.whatsapp_number or "",
        "whatsapp_number_2": row.whatsapp_number_2 or "",
        "viber_number": row.viber_number or "",
        "date_of_joining": row.date_of_joining or "",
        "department": row.department or "",
        "role": row.role or "",
        "location": row.location or "",
        "division": row.division or "",
        "supervisor_1": row.supervisor_1 or "",
        "supervisor_2": row.supervisor_2 or "",
        "bank": {
            "bsb": bank.get("bsb") or "",
            "account_number": bank.get("account_number") or "",
            "account_name": bank.get("account_name") or "",
            "bank_name": bank.get("bank_name") or "",
        },
    }


def vendor_fields_for_public(row: VendorMasterRecord) -> dict[str, Any]:
    billing = row.billing_address or {}
    bank = row.bank or {}
    return {
        "name": row.name or "",
        "aliases": row.aliases or [],
        "abn": row.abn or "",
        "contact_email": row.contact_email or "",
        "billing_address": {
            "street": billing.get("street") or "",
            "suburb": billing.get("suburb") or "",
            "postcode": billing.get("postcode") or "",
            "country": billing.get("country") or "",
        },
        "bank": {
            "bsb": bank.get("bsb") or "",
            "account_number": bank.get("account_number") or "",
            "account_name": bank.get("account_name") or "",
            "bank_name": bank.get("bank_name") or "",
        },
        "payment_terms": row.payment_terms or "",
    }


def _email_snapshot_fields(kind: MasterKind, fields: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(fields)
    bank = snapshot.get("bank")
    if isinstance(bank, dict) and bank.get("account_number"):
        bank = dict(bank)
        bank["account_number"] = _mask_account(str(bank["account_number"]))
        snapshot["bank"] = bank
    return snapshot


async def _invalidate_open_tokens(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: MasterKind,
    master_id: str,
) -> None:
    now = _utc_now()
    await session.execute(
        update(MasterConfirmationToken)
        .where(
            MasterConfirmationToken.tenant_id == tenant_id,
            MasterConfirmationToken.kind == kind,
            MasterConfirmationToken.master_id == master_id,
            MasterConfirmationToken.confirmed_at.is_(None),
            MasterConfirmationToken.expires_at > now,
        )
        .values(expires_at=now)
    )


async def send_master_confirmation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    kind: MasterKind,
    master_id: str,
) -> ConfirmationSendResult:
    await apply_rls_session_context(session, tenant_id)

    if kind == "employee":
        row = await get_employee_master_by_id(session, tenant_id, master_id)
        if not row:
            return ConfirmationSendResult(sent=False, error="Employee master not found")
        recipient = _employee_recipient(row)
        party_name = row.name or "Employee"
        fields = employee_fields_for_public(row)
    else:
        row = await get_vendor_master_by_id(session, tenant_id, master_id)
        if not row:
            return ConfirmationSendResult(sent=False, error="Vendor master not found")
        recipient = _vendor_recipient(row)
        party_name = row.name or "Vendor"
        fields = vendor_fields_for_public(row)

    if not recipient:
        return ConfirmationSendResult(
            sent=False,
            error="Contact email is required before sending confirmation",
        )

    token = secrets.token_urlsafe(32)
    expires_at = _utc_now() + timedelta(days=TOKEN_TTL_DAYS)
    await _invalidate_open_tokens(
        session,
        tenant_id=tenant_id,
        kind=kind,
        master_id=master_id,
    )
    session.add(
        MasterConfirmationToken(
            tenant_id=tenant_id,
            kind=kind,
            master_id=master_id,
            email=recipient,
            token_hash=_hash_token(token),
            snapshot=_email_snapshot_fields(kind, fields),
            expires_at=expires_at,
        )
    )

    confirm_url = _confirm_url(token)
    email_result: InviteEmailResult = await send_master_confirmation_email(
        to_email=recipient,
        party_name=party_name,
        kind=kind,
        confirm_url=confirm_url,
        fields=_email_snapshot_fields(kind, fields),
    )

    if not email_result.sent:
        await session.flush()
        return ConfirmationSendResult(
            sent=False,
            email=recipient,
            error=email_result.error or "Could not send confirmation email",
        )

    now = _utc_now()
    row.confirmation_sent_at = now
    if kind == "employee":
        row.status = EMPLOYEE_PENDING_STATUS
    else:
        row.status = VENDOR_PENDING_STATUS
    await session.flush()

    return ConfirmationSendResult(sent=True, email=recipient, expires_at=expires_at)


async def maybe_send_after_admin_change(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    kind: MasterKind,
    master_id: str,
    confirmable_changed: bool,
) -> ConfirmationSendResult | None:
    if not confirmable_changed:
        return None
    return await send_master_confirmation(
        session,
        tenant_id,
        kind=kind,
        master_id=master_id,
    )


async def _load_token_row(session: AsyncSession, token: str) -> MasterConfirmationToken:
    token_hash = _hash_token(token)
    await apply_platform_lookup_session(session)
    try:
        row = (
            await session.execute(
                select(MasterConfirmationToken).where(
                    MasterConfirmationToken.token_hash == token_hash
                )
            )
        ).scalar_one_or_none()
    finally:
        await clear_platform_lookup_session(session)
    if not row:
        raise HTTPException(404, "Confirmation link not found")
    return row


async def preview_master_confirmation(
    session: AsyncSession,
    *,
    token: str,
) -> ConfirmationPreview:
    token_row = await _load_token_row(session, token)
    now = _utc_now()
    expired = _as_utc(token_row.expires_at) <= now
    confirmed = token_row.confirmed_at is not None

    tenant = await session.get(Tenant, token_row.tenant_id)
    tenant_name = tenant.name if tenant else "Your organisation"

    await apply_rls_session_context(session, token_row.tenant_id)
    kind: MasterKind = "employee" if token_row.kind == "employee" else "vendor"
    if kind == "employee":
        master = await get_employee_master_by_id(session, token_row.tenant_id, token_row.master_id)
        if not master:
            raise HTTPException(404, "Employee master not found")
        fields = employee_fields_for_public(master)
        party_name = master.name or "Employee"
    else:
        master = await get_vendor_master_by_id(session, token_row.tenant_id, token_row.master_id)
        if not master:
            raise HTTPException(404, "Vendor master not found")
        fields = vendor_fields_for_public(master)
        party_name = master.name or "Vendor"

    return ConfirmationPreview(
        kind=kind,
        master_id=token_row.master_id,
        party_name=party_name,
        tenant_name=tenant_name,
        expired=expired,
        confirmed=confirmed,
        fields=fields,
    )


def _parse_bank(raw: Any) -> BankDetails:
    if not isinstance(raw, dict):
        raise HTTPException(400, "Invalid bank details")
    return BankDetails(
        bsb=str(raw.get("bsb") or "") or None,
        account_number=str(raw.get("account_number") or ""),
        account_name=str(raw.get("account_name") or ""),
        bank_name=str(raw.get("bank_name") or ""),
    )


def _parse_billing(raw: Any) -> BillingAddress:
    if not isinstance(raw, dict):
        raise HTTPException(400, "Invalid billing address")
    return BillingAddress(
        street=str(raw.get("street") or ""),
        suburb=str(raw.get("suburb") or ""),
        postcode=str(raw.get("postcode") or ""),
        country=str(raw.get("country") or ""),
    )


def _filter_allowed_fields(fields: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if key in allowed}


async def _ensure_unique_employee_email(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    *,
    master_id: str,
) -> None:
    key = (email or "").strip().lower()
    if not key:
        raise HTTPException(400, "Email is required")
    existing = await get_employee_master_by_email(session, tenant_id, key)
    if existing and existing.master_id != master_id:
        raise HTTPException(409, "Another employee already uses this email")


async def save_master_confirmation(
    session: AsyncSession,
    *,
    token: str,
    fields: dict[str, Any],
) -> ConfirmationSaveResult:
    token_row = await _load_token_row(session, token)
    if token_row.confirmed_at is not None:
        raise HTTPException(410, "This confirmation link has already been used")
    now = _utc_now()
    if _as_utc(token_row.expires_at) <= now:
        raise HTTPException(410, "Confirmation link expired")

    kind: MasterKind = "employee" if token_row.kind == "employee" else "vendor"
    allowed = EMPLOYEE_CONFIRM_FIELDS if kind == "employee" else VENDOR_CONFIRM_FIELDS
    fields = _filter_allowed_fields(fields, allowed)

    await apply_rls_session_context(session, token_row.tenant_id)

    if kind == "employee":
        before = await get_employee_master_by_id(
            session, token_row.tenant_id, token_row.master_id
        )
        if not before:
            raise HTTPException(404, "Employee master not found")

        name = str(fields.get("name") or "").strip()
        email = str(fields.get("email") or "").strip().lower()
        if not name:
            raise HTTPException(400, "Name is required")
        await _ensure_unique_employee_email(
            session,
            token_row.tenant_id,
            email,
            master_id=token_row.master_id,
        )

        patch = EmployeeMasterUpdate(
            name=name,
            email=email,
            whatsapp_number=str(fields.get("whatsapp_number") or ""),
            whatsapp_number_2=str(fields.get("whatsapp_number_2") or ""),
            viber_number=str(fields.get("viber_number") or "") or None,
            date_of_joining=str(fields.get("date_of_joining") or ""),
            department=str(fields.get("department") or ""),
            role=str(fields.get("role") or ""),
            location=str(fields.get("location") or ""),
            division=str(fields.get("division") or ""),
            supervisor_1=str(fields.get("supervisor_1") or ""),
            supervisor_2=str(fields.get("supervisor_2") or ""),
            bank=_parse_bank(fields.get("bank")),
            status=EMPLOYEE_ACTIVE_STATUS,
        )
        after = await update_employee_master(
            session,
            token_row.tenant_id,
            token_row.master_id,
            patch,
        )
        before_row = before
        party_name = after.name
        active_status = EMPLOYEE_ACTIVE_STATUS
    else:
        before = await get_vendor_master_by_id(
            session, token_row.tenant_id, token_row.master_id
        )
        if not before:
            raise HTTPException(404, "Vendor master not found")

        name = str(fields.get("name") or "").strip()
        contact_email = str(fields.get("contact_email") or "").strip().lower()
        if not name:
            raise HTTPException(400, "Name is required")
        if not contact_email:
            raise HTTPException(400, "Contact email is required")

        aliases_raw = fields.get("aliases")
        aliases: list[str]
        if isinstance(aliases_raw, list):
            aliases = [str(item).strip() for item in aliases_raw if str(item).strip()]
        elif isinstance(aliases_raw, str):
            aliases = [part.strip() for part in aliases_raw.split(",") if part.strip()]
        else:
            aliases = before.aliases or []

        patch = VendorMasterUpdate(
            name=name,
            aliases=aliases,
            abn=str(fields.get("abn") or ""),
            contact_email=contact_email,
            billing_address=_parse_billing(fields.get("billing_address")),
            bank=_parse_bank(fields.get("bank")),
            payment_terms=str(fields.get("payment_terms") or ""),
            status=VENDOR_ACTIVE_STATUS,
        )
        after = await update_vendor_master(
            session,
            token_row.tenant_id,
            token_row.master_id,
            patch,
        )
        before_row = before
        party_name = after.name
        active_status = VENDOR_ACTIVE_STATUS

    confirmed_at = _utc_now()
    token_row.confirmed_at = confirmed_at
    if kind == "employee":
        emp_row = await get_employee_master_by_id(
            session, token_row.tenant_id, token_row.master_id
        )
        if emp_row:
            emp_row.confirmed_at = confirmed_at
    else:
        vendor_row = await get_vendor_master_by_id(
            session, token_row.tenant_id, token_row.master_id
        )
        if vendor_row:
            vendor_row.confirmed_at = confirmed_at

    await log_event(
        session,
        "master_data_self_confirmed",
        tenant_id=token_row.tenant_id,
        detail={
            "kind": kind,
            "master_id": token_row.master_id,
            "email": token_row.email,
            "before": employee_fields_for_public(before_row)
            if kind == "employee"
            else vendor_fields_for_public(before_row),
            "after": fields,
        },
        actor_name=party_name,
        actor_email=token_row.email,
    )
    await session.flush()

    return ConfirmationSaveResult(
        kind=kind,
        master_id=token_row.master_id,
        party_name=party_name,
        status=active_status,
        confirmed_at=confirmed_at,
    )
