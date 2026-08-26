"""Vendor/employee master CRUD and rule book config sync."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.models.pending_vendor import PendingVendor
from app.models.vendor_master import VendorMasterRecord
from app.schemas.master_data import (
    EmployeeMasterCreate,
    EmployeeMasterResponse,
    EmployeeMasterUpdate,
    PendingVendorCreate,
    PendingVendorPromote,
    PendingVendorResponse,
    VendorMasterCreate,
    VendorMasterResponse,
    VendorMasterUpdate,
)
from app.schemas.rule_book_config import BillingAddress, EmployeeMaster, RuleBookConfigPayload, VendorMaster
from app.services.rule_book.rule_book_config_io import (
    load_legacy_file_dict_with_masters,
    load_rule_book_config_dict,
)
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
from app.services.shared.bank_masking import merge_bank_update
from app.tenant_scoped import coerce_tenant_uuid


def _tenant_id(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    resolved = coerce_tenant_uuid(tenant_id)
    if resolved is None:
        raise ValueError("Invalid tenant_id")
    return resolved


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "vendor"


def _new_master_id(prefix: str, name: str) -> str:
    base = f"{prefix}-{_slugify(name)}"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _normalize_abn(abn: str | None) -> str:
    if not abn:
        return ""
    return re.sub(r"\D", "", abn.strip())[:11]


def vendor_record_to_schema(row: VendorMasterRecord) -> VendorMasterResponse:
    return VendorMasterResponse(
        db_id=row.id,
        id=row.master_id,
        name=row.name,
        aliases=row.aliases or [],
        abn=row.abn or "",
        billing_address=row.billing_address or {},
        bank=row.bank or {},
        default_ledger=row.default_ledger or "",
        default_sub_ledger=row.default_sub_ledger or "",
        payment_terms=row.payment_terms or "",
        status=row.status or "",
        registered_on=row.registered_on or "",
        total_spend_ytd=row.total_spend_ytd or 0,
        invoice_count=row.invoice_count or 0,
        match_confidence=row.match_confidence or 0,
        contact_email=row.contact_email or "",
        contact_phone=row.contact_phone or "",
        confirmation_sent_at=row.confirmation_sent_at,
        confirmed_at=row.confirmed_at,
    )


def employee_record_to_schema(row: EmployeeMasterRecord) -> EmployeeMasterResponse:
    return EmployeeMasterResponse(
        db_id=row.id,
        id=row.master_id,
        name=row.name,
        role=row.role or "",
        email=row.email or "",
        whatsapp_number=row.whatsapp_number or "",
        whatsapp_number_2=row.whatsapp_number_2 or "",
        viber_number=row.viber_number,
        date_of_joining=row.date_of_joining or "",
        department=row.department or "",
        location=row.location or "",
        division=row.division or "",
        supervisor_1=row.supervisor_1 or "",
        supervisor_2=row.supervisor_2 or "",
        bank=row.bank or {},
        spending_limits=row.spending_limits or {},
        advance_parent_ledger=row.advance_parent_ledger or "",
        advance_sub_ledger=row.advance_sub_ledger or "",
        ytd_spent=row.ytd_spent or 0,
        mtd_spent=row.mtd_spent or 0,
        qtd_spent=row.qtd_spent or 0,
        claim_count=row.claim_count or 0,
        last_claim=row.last_claim or "",
        status=row.status or "",
        confirmation_sent_at=row.confirmation_sent_at,
        confirmed_at=row.confirmed_at,
    )


def vendor_master_to_dict(vendor: VendorMaster) -> dict[str, Any]:
    data = vendor.model_dump()
    data.pop("db_id", None)
    data.pop("bank_masked", None)
    return data


def employee_master_to_dict(employee: EmployeeMaster) -> dict[str, Any]:
    data = employee.model_dump(by_alias=True)
    data.pop("db_id", None)
    data.pop("advance_balance", None)
    data.pop("bank_masked", None)
    # Keep legacy key for rule-book file consumers.
    if "spending_limits" in data and "budget" not in data:
        data["budget"] = data["spending_limits"]
    return data


async def count_vendor_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> int:
    tid = _tenant_id(tenant_id)
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(VendorMasterRecord)
                .where(VendorMasterRecord.tenant_id == tid)
            )
        ).scalar_one()
    )


async def count_employee_masters(db: AsyncSession, tenant_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(EmployeeMasterRecord)
                .where(EmployeeMasterRecord.tenant_id == tenant_id)
            )
        ).scalar_one()
    )


async def import_masters_from_config_file(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """One-time import of embedded JSON masters into Postgres."""
    raw = load_legacy_file_dict_with_masters(tenant_id)
    if raw is None:
        raw = await load_rule_book_config_dict(db, tenant_id)
    for item in raw.get("vendor_masters") or []:
        master_id = str(item.get("id") or _new_master_id("vm", str(item.get("name", "vendor"))))
        existing = (
            await db.execute(
                select(VendorMasterRecord).where(
                    VendorMasterRecord.tenant_id == tenant_id,
                    VendorMasterRecord.master_id == master_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            VendorMasterRecord(
                tenant_id=tenant_id,
                master_id=master_id,
                name=str(item.get("name", "")),
                aliases=item.get("aliases") or [],
                abn=str(item.get("abn") or ""),
                billing_address=item.get("billing_address") or {},
                bank=item.get("bank") or {},
                default_ledger=str(item.get("default_ledger") or ""),
                default_sub_ledger=str(item.get("default_sub_ledger") or ""),
                payment_terms=str(item.get("payment_terms") or ""),
                status=str(item.get("status") or ""),
                registered_on=str(item.get("registered_on") or ""),
                total_spend_ytd=float(item.get("total_spend_ytd") or 0),
                invoice_count=int(item.get("invoice_count") or 0),
                match_confidence=float(item.get("match_confidence") or 0),
                contact_email=str(item.get("contact_email") or ""),
                contact_phone=str(item.get("contact_phone") or ""),
            )
        )

    for item in raw.get("employee_masters") or []:
        master_id = str(item.get("id") or _new_master_id("em", str(item.get("name", "employee"))))
        existing = (
            await db.execute(
                select(EmployeeMasterRecord).where(
                    EmployeeMasterRecord.tenant_id == tenant_id,
                    EmployeeMasterRecord.master_id == master_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            EmployeeMasterRecord(
                tenant_id=tenant_id,
                master_id=master_id,
                name=str(item.get("name", "")),
                role=str(item.get("role") or ""),
                email=str(item.get("email") or ""),
                whatsapp_number=str(item.get("whatsapp_number") or ""),
                whatsapp_number_2=str(item.get("whatsapp_number_2") or ""),
                viber_number=item.get("viber_number"),
                date_of_joining=str(item.get("date_of_joining") or ""),
                department=str(item.get("department") or ""),
                location=str(item.get("location") or ""),
                division=str(item.get("division") or ""),
                supervisor_1=str(item.get("supervisor_1") or ""),
                supervisor_2=str(item.get("supervisor_2") or ""),
                bank=item.get("bank") or {},
                spending_limits=item.get("spending_limits") or item.get("budget") or {},
                advance_parent_ledger=str(item.get("advance_parent_ledger") or ""),
                advance_sub_ledger=str(item.get("advance_sub_ledger") or ""),
                ytd_spent=float(item.get("ytd_spent") or 0),
                mtd_spent=float(item.get("mtd_spent") or 0),
                qtd_spent=float(item.get("qtd_spent") or 0),
                claim_count=int(item.get("claim_count") or 0),
                last_claim=str(item.get("last_claim") or ""),
                status=str(item.get("status") or ""),
            )
        )
    await db.flush()


async def ensure_masters_imported(db: AsyncSession, tenant_id: int) -> None:
    vendor_count = await count_vendor_masters(db, tenant_id)
    employee_count = await count_employee_masters(db, tenant_id)
    if vendor_count == 0 and employee_count == 0:
        await import_masters_from_config_file(db, tenant_id)


async def list_vendor_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> list[VendorMasterResponse]:
    tid = _tenant_id(tenant_id)
    rows = (
        await db.execute(
            select(VendorMasterRecord)
            .where(VendorMasterRecord.tenant_id == tid)
            .order_by(VendorMasterRecord.name)
        )
    ).scalars().all()
    if not rows:
        await ensure_masters_imported(db, tid)
        rows = (
            await db.execute(
                select(VendorMasterRecord)
                .where(VendorMasterRecord.tenant_id == tid)
                .order_by(VendorMasterRecord.name)
            )
        ).scalars().all()
    return [vendor_record_to_schema(row) for row in rows]


async def classification_config_with_db_masters(
    db: AsyncSession,
    tenant_id: int,
    config: RuleBookConfigPayload,
) -> RuleBookConfigPayload:
    """Merge DB masters into rule book config for pipeline evaluation."""
    vendors = await list_vendor_masters(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    updates: dict[str, list] = {}
    if vendors:
        updates["vendor_masters"] = vendors
    if employees:
        updates["employee_masters"] = employees
    if not updates:
        return config
    return config.model_copy(update=updates)


async def _attach_employee_advance_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    employees: list[EmployeeMasterResponse],
) -> None:
    """Stamp read-only advance_balance from Staff Advance journals onto response rows."""
    if not employees:
        return
    from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
    from app.services.purchase.team_expense_advance_service import (
        employee_advance_balances_by_ids,
    )

    tid = _tenant_id(tenant_id)
    config = await load_posting_config_for_tenant(db, tid)
    balances = await employee_advance_balances_by_ids(db, tid, config, employees)
    for employee in employees:
        employee.advance_balance = float(balances.get(employee.id, Decimal("0")))


async def list_employee_masters(
    db: AsyncSession,
    tenant_id: int,
    *,
    include_advance_balances: bool = True,
) -> list[EmployeeMasterResponse]:
    rows = (
        await db.execute(
            select(EmployeeMasterRecord)
            .where(EmployeeMasterRecord.tenant_id == tenant_id)
            .order_by(EmployeeMasterRecord.name)
        )
    ).scalars().all()
    if not rows:
        await ensure_masters_imported(db, tenant_id)
        rows = (
            await db.execute(
                select(EmployeeMasterRecord)
                .where(EmployeeMasterRecord.tenant_id == tenant_id)
                .order_by(EmployeeMasterRecord.name)
            )
        ).scalars().all()
    employees = [employee_record_to_schema(row) for row in rows]
    if include_advance_balances:
        await _attach_employee_advance_balances(db, tenant_id, employees)
    return employees


async def get_vendor_master_by_id(
    db: AsyncSession,
    tenant_id: int,
    master_id: str,
) -> VendorMasterRecord | None:
    return (
        await db.execute(
            select(VendorMasterRecord).where(
                VendorMasterRecord.tenant_id == tenant_id,
                VendorMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one_or_none()


async def get_employee_master_by_id(
    db: AsyncSession,
    tenant_id: int,
    master_id: str,
) -> EmployeeMasterRecord | None:
    return (
        await db.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.tenant_id == tenant_id,
                EmployeeMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one_or_none()


async def get_employee_master_by_email(
    db: AsyncSession,
    tenant_id: int,
    email: str,
) -> EmployeeMasterRecord | None:
    key = (email or "").strip().lower()
    if not key:
        return None
    from sqlalchemy import func

    return (
        await db.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.tenant_id == tenant_id,
                func.lower(EmployeeMasterRecord.email) == key,
            )
        )
    ).scalar_one_or_none()


async def sync_masters_to_config_file(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """No-op: masters live in Postgres and are merged at read time."""
    clear_classification_config_cache()


async def create_vendor_master(
    db: AsyncSession,
    tenant_id: int,
    body: VendorMasterCreate,
) -> VendorMasterResponse:
    await ensure_masters_imported(db, tenant_id)
    master_id = body.master_id or _new_master_id("vm", body.name)
    existing = await get_vendor_master_by_id(db, tenant_id, master_id)
    if existing:
        raise ValueError(f"Vendor master id '{master_id}' already exists")

    row = VendorMasterRecord(
        tenant_id=tenant_id,
        master_id=master_id,
        name=body.name,
        aliases=body.aliases,
        abn=_normalize_abn(body.abn),
        billing_address=body.billing_address.model_dump(),
        bank=merge_bank_update({}, body.bank.model_dump(exclude_none=True)),
        default_ledger=body.default_ledger,
        default_sub_ledger=body.default_sub_ledger,
        payment_terms=body.payment_terms,
        status=body.status,
        registered_on=body.registered_on,
        total_spend_ytd=body.total_spend_ytd,
        invoice_count=body.invoice_count,
        match_confidence=body.match_confidence,
        contact_email=(body.contact_email or "").strip(),
        contact_phone=(body.contact_phone or "").strip(),
    )
    db.add(row)
    await db.flush()
    await sync_masters_to_config_file(db, tenant_id)
    return vendor_record_to_schema(row)


async def update_vendor_master(
    db: AsyncSession,
    tenant_id: int,
    master_id: str,
    body: VendorMasterUpdate,
) -> VendorMasterResponse:
    row = await get_vendor_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Vendor master not found")

    patch = body.model_dump(exclude_unset=True)
    if "abn" in patch and patch["abn"] is not None:
        patch["abn"] = _normalize_abn(patch["abn"])
    if "contact_phone" in patch and patch["contact_phone"] is not None:
        patch["contact_phone"] = str(patch["contact_phone"]).strip()
    if "contact_email" in patch and patch["contact_email"] is not None:
        patch["contact_email"] = str(patch["contact_email"]).strip()
    if "bank" in patch and body.bank is not None:
        patch["bank"] = merge_bank_update(
            row.bank or {},
            body.bank.model_dump(exclude_unset=True, exclude_none=True),
        )
    for key, value in patch.items():
        if key == "billing_address" and value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump(exclude_unset=True, exclude_none=True)
        setattr(row, key, value)
    await db.flush()
    await sync_masters_to_config_file(db, tenant_id)
    return vendor_record_to_schema(row)


async def delete_vendor_master(db: AsyncSession, tenant_id: int, master_id: str) -> None:
    row = await get_vendor_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Vendor master not found")
    await db.delete(row)
    await db.flush()
    await sync_masters_to_config_file(db, tenant_id)


async def _default_employee_advance_parent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> str:
    """Prefer Team Expenses posting default when it exists in the live COA."""
    from app.services.master_data.party_coa_subledger_service import find_coa_entry_by_name
    from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
    from app.schemas.rule_book_config import validate_rule_book_config_payload

    raw = await load_rule_book_config_dict(db, tenant_id)
    config = validate_rule_book_config_payload(raw)
    label = (config.team_expense_posting.default_advance_parent_ledger or "").strip()
    if not label:
        return ""
    if find_coa_entry_by_name(list(config.chart_of_accounts or []), label) is None:
        return ""
    return label


async def create_employee_master(
    db: AsyncSession,
    tenant_id: int,
    body: EmployeeMasterCreate,
) -> EmployeeMasterResponse:
    await ensure_masters_imported(db, tenant_id)
    master_id = body.master_id or _new_master_id("em", body.name)
    existing = await get_employee_master_by_id(db, tenant_id, master_id)
    if existing:
        raise ValueError(f"Employee master id '{master_id}' already exists")

    advance_parent = (body.advance_parent_ledger or "").strip()
    if not advance_parent:
        advance_parent = await _default_employee_advance_parent(db, tenant_id)

    row = EmployeeMasterRecord(
        tenant_id=tenant_id,
        master_id=master_id,
        name=body.name,
        role=body.role,
        email=body.email,
        whatsapp_number=body.whatsapp_number,
        whatsapp_number_2=body.whatsapp_number_2,
        viber_number=body.viber_number,
        date_of_joining=body.date_of_joining,
        department=body.department,
        location=body.location,
        division=body.division,
        supervisor_1=body.supervisor_1,
        supervisor_2=body.supervisor_2,
        bank=merge_bank_update({}, body.bank.model_dump(exclude_none=True)),
        spending_limits=body.spending_limits.model_dump(),
        advance_parent_ledger=advance_parent,
        ytd_spent=body.ytd_spent,
        mtd_spent=body.mtd_spent,
        qtd_spent=body.qtd_spent,
        claim_count=body.claim_count,
        last_claim=body.last_claim,
        status=body.status,
    )
    db.add(row)
    await db.flush()
    await _sync_employee_advance_sub_ledger(db, tenant_id, row)
    await sync_masters_to_config_file(db, tenant_id)
    employee = employee_record_to_schema(row)
    await _attach_employee_advance_balances(db, tenant_id, [employee])
    return employee


async def _sync_employee_advance_sub_ledger(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    row: EmployeeMasterRecord,
) -> None:
    """Create/refresh the employee's COA advance child under their selected parent."""
    from app.services.master_data.party_coa_subledger_service import (
        ensure_employee_party_coa_sub_ledger,
    )

    child = await ensure_employee_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.master_id,
        employee_name=row.name,
        parent_ledger_name=row.advance_parent_ledger or "",
    )
    row.advance_sub_ledger = child.account_name if child else ""
    await db.flush()


async def update_employee_master(
    db: AsyncSession,
    tenant_id: int,
    master_id: str,
    body: EmployeeMasterUpdate,
) -> EmployeeMasterResponse:
    row = await get_employee_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Employee master not found")

    patch = body.model_dump(exclude_unset=True)
    if "budget" in patch and "spending_limits" not in patch:
        patch["spending_limits"] = patch.pop("budget")
    else:
        patch.pop("budget", None)
    for key, value in patch.items():
        if key == "bank" and body.bank is not None:
            value = merge_bank_update(
                row.bank or {},
                body.bank.model_dump(exclude_unset=True, exclude_none=True),
            )
        elif key == "spending_limits" and value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump()
        if key == "advance_parent_ledger" and value is not None:
            value = str(value).strip()
        setattr(row, key, value)
    await db.flush()
    if {"advance_parent_ledger", "name"} & set(patch):
        await _sync_employee_advance_sub_ledger(db, tenant_id, row)
    await sync_masters_to_config_file(db, tenant_id)
    employee = employee_record_to_schema(row)
    await _attach_employee_advance_balances(db, tenant_id, [employee])
    return employee


async def delete_employee_master(db: AsyncSession, tenant_id: int, master_id: str) -> None:
    row = await get_employee_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Employee master not found")
    await db.delete(row)
    await db.flush()
    await sync_masters_to_config_file(db, tenant_id)


async def list_pending_vendors(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> list[PendingVendorResponse]:
    tid = _tenant_id(tenant_id)
    rows = (
        await db.execute(
            select(PendingVendor)
            .where(
                PendingVendor.tenant_id == tid,
                PendingVendor.status == "pending",
            )
            .order_by(PendingVendor.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return []
    await _dismiss_pending_matching_masters(db, tid, pending=rows)
    remaining = [row for row in rows if row.status == "pending"]
    return [PendingVendorResponse.model_validate(row) for row in remaining]


async def _vendor_masters_for_match(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[VendorMaster]:
    rows = (
        await db.execute(
            select(
                VendorMasterRecord.master_id,
                VendorMasterRecord.name,
                VendorMasterRecord.aliases,
                VendorMasterRecord.abn,
            ).where(VendorMasterRecord.tenant_id == tenant_id)
        )
    ).all()
    return [
        VendorMaster(
            id=str(row.master_id),
            name=row.name,
            aliases=list(row.aliases or []),
            abn=row.abn or "",
        )
        for row in rows
    ]


async def _dismiss_pending_matching_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    pending: list[PendingVendor] | None = None,
) -> None:
    """Remove queue rows when the vendor is already registered in masters."""
    from app.services.master_data.vendor_detection import find_matching_vendor_master

    tid = _tenant_id(tenant_id)
    if pending is None:
        pending = (
            await db.execute(
                select(PendingVendor).where(
                    PendingVendor.tenant_id == tid,
                    PendingVendor.status == "pending",
                )
            )
        ).scalars().all()
    if not pending:
        return
    masters = await _vendor_masters_for_match(db, tid)
    changed = False
    for row in pending:
        if find_matching_vendor_master(row.detected_name, row.detected_abn, masters):
            row.status = "dismissed"
            row.resolved_at = datetime.now(UTC)
            changed = True
    if changed:
        await db.flush()


async def create_pending_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    body: PendingVendorCreate,
) -> PendingVendorResponse:
    from app.services.master_data.vendor_detection import find_matching_vendor_master

    tid = _tenant_id(tenant_id)
    masters = await list_vendor_masters(db, tid)
    if find_matching_vendor_master(body.detected_name, body.detected_abn, masters):
        raise ValueError("Vendor already registered in master data")

    existing = (
        await db.execute(
            select(PendingVendor).where(
                PendingVendor.tenant_id == tid,
                PendingVendor.status == "pending",
            )
        )
    ).scalars().all()
    name_key = body.detected_name.strip().lower()
    for row in existing:
        if row.detected_name.strip().lower() == name_key:
            return PendingVendorResponse.model_validate(row)

    row = PendingVendor(
        tenant_id=tid,
        detected_name=body.detected_name,
        detected_abn=body.detected_abn,
        detected_address=body.detected_address,
        source_invoice_id=body.source_invoice_id,
        confidence=body.confidence,
        status="pending",
    )
    db.add(row)
    await db.flush()
    return PendingVendorResponse.model_validate(row)


async def dismiss_pending_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    pending_id: int,
) -> None:
    tid = _tenant_id(tenant_id)
    row = await db.get(PendingVendor, pending_id)
    if not row or row.tenant_id != tid:
        raise LookupError("Pending vendor not found")
    row.status = "dismissed"
    row.resolved_at = datetime.now(UTC)
    await db.flush()


async def promote_pending_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    pending_id: int,
    body: PendingVendorPromote,
) -> VendorMasterResponse:
    tid = _tenant_id(tenant_id)
    row = await db.get(PendingVendor, pending_id)
    if not row or row.tenant_id != tid or row.status != "pending":
        raise LookupError("Pending vendor not found")

    from app.services.master_data.vendor_detection import find_matching_vendor_master

    masters = await list_vendor_masters(db, tid)
    if body.master_id:
        explicit_row = await get_vendor_master_by_id(db, tid, body.master_id)
        if explicit_row is not None:
            existing = vendor_record_to_schema(explicit_row)
            row.status = "promoted"
            row.promoted_master_id = existing.id
            row.resolved_at = datetime.now(UTC)
            await db.flush()
            from app.services.master_data.vendor_hold_service import release_invoices_after_vendor_promotion

            await release_invoices_after_vendor_promotion(
                db,
                tid,
                vendor_name=existing.name,
                source_invoice_id=row.source_invoice_id,
            )
            from app.services.master_data.registry_promotion_service import (
                sync_vendor_registry_after_promotion,
            )

            await sync_vendor_registry_after_promotion(
                db,
                tenant_id=tid,
                name=existing.name,
                abn=existing.abn,
                source_invoice_id=row.source_invoice_id,
            )
            return existing

    existing = find_matching_vendor_master(row.detected_name, row.detected_abn, masters)
    if existing is not None:
        row.status = "promoted"
        row.promoted_master_id = existing.id
        row.resolved_at = datetime.now(UTC)
        await db.flush()
        from app.services.master_data.vendor_hold_service import release_invoices_after_vendor_promotion

        await release_invoices_after_vendor_promotion(
            db,
            tid,
            vendor_name=existing.name,
            source_invoice_id=row.source_invoice_id,
        )
        from app.services.master_data.registry_promotion_service import (
            sync_vendor_registry_after_promotion,
        )

        await sync_vendor_registry_after_promotion(
            db,
            tenant_id=tid,
            name=existing.name,
            abn=existing.abn,
            source_invoice_id=row.source_invoice_id,
        )
        return existing

    name = body.name or row.detected_name
    master_id = body.master_id or _new_master_id("vm", name)
    vendor = await create_vendor_master(
        db,
        tid,
        VendorMasterCreate(
            master_id=master_id,
            name=name,
            abn=body.abn or (row.detected_abn or ""),
            default_ledger=body.default_ledger,
            status=body.status,
            match_confidence=row.confidence,
            billing_address=BillingAddress(street=row.detected_address or ""),
        ),
    )
    row.status = "promoted"
    row.promoted_master_id = vendor.id
    row.resolved_at = datetime.now(UTC)
    await db.flush()

    from app.services.master_data.vendor_hold_service import release_invoices_after_vendor_promotion

    await release_invoices_after_vendor_promotion(
        db,
        tid,
        vendor_name=name,
        source_invoice_id=row.source_invoice_id,
    )
    from app.services.master_data.registry_promotion_service import (
        sync_vendor_registry_after_promotion,
    )

    await sync_vendor_registry_after_promotion(
        db,
        tenant_id=tid,
        name=name,
        abn=vendor.abn,
        source_invoice_id=row.source_invoice_id,
    )
    return vendor


async def attach_masters_to_config_dict(
    db: AsyncSession,
    tenant_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Merge DB masters into a rule book config dict for API responses."""
    vendors = await list_vendor_masters(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    merged = dict(data)
    merged["vendor_masters"] = [vendor_master_to_dict(v) for v in vendors]
    merged["employee_masters"] = [employee_master_to_dict(e) for e in employees]
    return merged
