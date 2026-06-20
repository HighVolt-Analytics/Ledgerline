"""Vendor/employee master CRUD and rule book config sync."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
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
from app.services.rule_book_config_io import (
    load_rule_book_config_dict,
    org_rule_book_config_path,
)
from app.services.rule_book_mapper import clear_classification_config_cache


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
    )


def employee_record_to_schema(row: EmployeeMasterRecord) -> EmployeeMasterResponse:
    return EmployeeMasterResponse(
        db_id=row.id,
        id=row.master_id,
        name=row.name,
        role=row.role or "",
        email=row.email or "",
        whatsapp_number=row.whatsapp_number or "",
        viber_number=row.viber_number,
        bank=row.bank or {},
        budget=row.budget or {},
        ytd_spent=row.ytd_spent or 0,
        mtd_spent=row.mtd_spent or 0,
        qtd_spent=row.qtd_spent or 0,
        claim_count=row.claim_count or 0,
        last_claim=row.last_claim or "",
        status=row.status or "",
    )


def vendor_master_to_dict(vendor: VendorMaster) -> dict[str, Any]:
    data = vendor.model_dump()
    data.pop("db_id", None)
    return data


def employee_master_to_dict(employee: EmployeeMaster) -> dict[str, Any]:
    data = employee.model_dump()
    data.pop("db_id", None)
    return data


async def count_vendor_masters(db: AsyncSession, org_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(VendorMasterRecord)
                .where(VendorMasterRecord.org_id == org_id)
            )
        ).scalar_one()
    )


async def count_employee_masters(db: AsyncSession, org_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(EmployeeMasterRecord)
                .where(EmployeeMasterRecord.org_id == org_id)
            )
        ).scalar_one()
    )


async def import_masters_from_config_file(db: AsyncSession, org_id: int) -> None:
    """One-time import of embedded JSON masters into Postgres."""
    raw = load_rule_book_config_dict(org_id)
    for item in raw.get("vendor_masters") or []:
        master_id = str(item.get("id") or _new_master_id("vm", str(item.get("name", "vendor"))))
        existing = (
            await db.execute(
                select(VendorMasterRecord).where(
                    VendorMasterRecord.org_id == org_id,
                    VendorMasterRecord.master_id == master_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            VendorMasterRecord(
                org_id=org_id,
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
            )
        )

    for item in raw.get("employee_masters") or []:
        master_id = str(item.get("id") or _new_master_id("em", str(item.get("name", "employee"))))
        existing = (
            await db.execute(
                select(EmployeeMasterRecord).where(
                    EmployeeMasterRecord.org_id == org_id,
                    EmployeeMasterRecord.master_id == master_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            EmployeeMasterRecord(
                org_id=org_id,
                master_id=master_id,
                name=str(item.get("name", "")),
                role=str(item.get("role") or ""),
                email=str(item.get("email") or ""),
                whatsapp_number=str(item.get("whatsapp_number") or ""),
                viber_number=item.get("viber_number"),
                bank=item.get("bank") or {},
                budget=item.get("budget") or {},
                ytd_spent=float(item.get("ytd_spent") or 0),
                mtd_spent=float(item.get("mtd_spent") or 0),
                qtd_spent=float(item.get("qtd_spent") or 0),
                claim_count=int(item.get("claim_count") or 0),
                last_claim=str(item.get("last_claim") or ""),
                status=str(item.get("status") or ""),
            )
        )
    await db.flush()


async def ensure_masters_imported(db: AsyncSession, org_id: int) -> None:
    vendor_count = await count_vendor_masters(db, org_id)
    employee_count = await count_employee_masters(db, org_id)
    if vendor_count == 0 and employee_count == 0:
        await import_masters_from_config_file(db, org_id)


async def list_vendor_masters(db: AsyncSession, org_id: int) -> list[VendorMasterResponse]:
    await ensure_masters_imported(db, org_id)
    rows = (
        await db.execute(
            select(VendorMasterRecord)
            .where(VendorMasterRecord.org_id == org_id)
            .order_by(VendorMasterRecord.name)
        )
    ).scalars().all()
    return [vendor_record_to_schema(row) for row in rows]


async def classification_config_with_db_masters(
    db: AsyncSession,
    org_id: int,
    config: RuleBookConfigPayload,
) -> RuleBookConfigPayload:
    """Merge DB masters into rule book config for pipeline evaluation."""
    vendors = await list_vendor_masters(db, org_id)
    employees = await list_employee_masters(db, org_id)
    updates: dict[str, list] = {}
    if vendors:
        updates["vendor_masters"] = vendors
    if employees:
        updates["employee_masters"] = employees
    if not updates:
        return config
    return config.model_copy(update=updates)


async def list_employee_masters(db: AsyncSession, org_id: int) -> list[EmployeeMasterResponse]:
    await ensure_masters_imported(db, org_id)
    rows = (
        await db.execute(
            select(EmployeeMasterRecord)
            .where(EmployeeMasterRecord.org_id == org_id)
            .order_by(EmployeeMasterRecord.name)
        )
    ).scalars().all()
    return [employee_record_to_schema(row) for row in rows]


async def get_vendor_master_by_id(
    db: AsyncSession,
    org_id: int,
    master_id: str,
) -> VendorMasterRecord | None:
    return (
        await db.execute(
            select(VendorMasterRecord).where(
                VendorMasterRecord.org_id == org_id,
                VendorMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one_or_none()


async def get_employee_master_by_id(
    db: AsyncSession,
    org_id: int,
    master_id: str,
) -> EmployeeMasterRecord | None:
    return (
        await db.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.org_id == org_id,
                EmployeeMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one_or_none()


async def get_employee_master_by_email(
    db: AsyncSession,
    org_id: int,
    email: str,
) -> EmployeeMasterRecord | None:
    key = (email or "").strip().lower()
    if not key:
        return None
    from sqlalchemy import func

    return (
        await db.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.org_id == org_id,
                func.lower(EmployeeMasterRecord.email) == key,
            )
        )
    ).scalar_one_or_none()


async def sync_masters_to_config_file(db: AsyncSession, org_id: int) -> None:
    """Write current DB masters into the org rule book JSON for the mapping engine."""
    vendors = await list_vendor_masters(db, org_id)
    employees = await list_employee_masters(db, org_id)
    path = org_rule_book_config_path(org_id)
    if not path.is_file():
        load_rule_book_config_dict(org_id)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data["vendor_masters"] = [vendor_master_to_dict(v) for v in vendors]
    data["employee_masters"] = [employee_master_to_dict(e) for e in employees]
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
    except OSError as exc:
        raise ValueError(f"Could not sync vendor masters to rule book file: {exc}") from exc
    clear_classification_config_cache()


async def create_vendor_master(
    db: AsyncSession,
    org_id: int,
    body: VendorMasterCreate,
) -> VendorMasterResponse:
    await ensure_masters_imported(db, org_id)
    master_id = body.master_id or _new_master_id("vm", body.name)
    existing = await get_vendor_master_by_id(db, org_id, master_id)
    if existing:
        raise ValueError(f"Vendor master id '{master_id}' already exists")

    row = VendorMasterRecord(
        org_id=org_id,
        master_id=master_id,
        name=body.name,
        aliases=body.aliases,
        abn=_normalize_abn(body.abn),
        billing_address=body.billing_address.model_dump(),
        bank=body.bank.model_dump(exclude_none=True),
        default_ledger=body.default_ledger,
        default_sub_ledger=body.default_sub_ledger,
        payment_terms=body.payment_terms,
        status=body.status,
        registered_on=body.registered_on,
        total_spend_ytd=body.total_spend_ytd,
        invoice_count=body.invoice_count,
        match_confidence=body.match_confidence,
    )
    db.add(row)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)
    return vendor_record_to_schema(row)


async def update_vendor_master(
    db: AsyncSession,
    org_id: int,
    master_id: str,
    body: VendorMasterUpdate,
) -> VendorMasterResponse:
    row = await get_vendor_master_by_id(db, org_id, master_id)
    if not row:
        raise LookupError("Vendor master not found")

    patch = body.model_dump(exclude_unset=True)
    if "abn" in patch and patch["abn"] is not None:
        patch["abn"] = _normalize_abn(patch["abn"])
    for key, value in patch.items():
        if key in {"billing_address", "bank"} and value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump(exclude_none=True)
        setattr(row, key, value)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)
    return vendor_record_to_schema(row)


async def delete_vendor_master(db: AsyncSession, org_id: int, master_id: str) -> None:
    row = await get_vendor_master_by_id(db, org_id, master_id)
    if not row:
        raise LookupError("Vendor master not found")
    await db.delete(row)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)


async def create_employee_master(
    db: AsyncSession,
    org_id: int,
    body: EmployeeMasterCreate,
) -> EmployeeMasterResponse:
    await ensure_masters_imported(db, org_id)
    master_id = body.master_id or _new_master_id("em", body.name)
    existing = await get_employee_master_by_id(db, org_id, master_id)
    if existing:
        raise ValueError(f"Employee master id '{master_id}' already exists")

    row = EmployeeMasterRecord(
        org_id=org_id,
        master_id=master_id,
        name=body.name,
        role=body.role,
        email=body.email,
        whatsapp_number=body.whatsapp_number,
        viber_number=body.viber_number,
        bank=body.bank.model_dump(exclude_none=True),
        budget=body.budget.model_dump(),
        ytd_spent=body.ytd_spent,
        mtd_spent=body.mtd_spent,
        qtd_spent=body.qtd_spent,
        claim_count=body.claim_count,
        last_claim=body.last_claim,
        status=body.status,
    )
    db.add(row)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)
    return employee_record_to_schema(row)


async def update_employee_master(
    db: AsyncSession,
    org_id: int,
    master_id: str,
    body: EmployeeMasterUpdate,
) -> EmployeeMasterResponse:
    row = await get_employee_master_by_id(db, org_id, master_id)
    if not row:
        raise LookupError("Employee master not found")

    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key in {"bank", "budget"} and value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump(exclude_none=True) if key == "bank" else value.model_dump()
        setattr(row, key, value)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)
    return employee_record_to_schema(row)


async def delete_employee_master(db: AsyncSession, org_id: int, master_id: str) -> None:
    row = await get_employee_master_by_id(db, org_id, master_id)
    if not row:
        raise LookupError("Employee master not found")
    await db.delete(row)
    await db.flush()
    await sync_masters_to_config_file(db, org_id)


async def list_pending_vendors(db: AsyncSession, org_id: int) -> list[PendingVendorResponse]:
    await _dismiss_pending_matching_masters(db, org_id)
    rows = (
        await db.execute(
            select(PendingVendor)
            .where(
                PendingVendor.org_id == org_id,
                PendingVendor.status == "pending",
            )
            .order_by(PendingVendor.created_at.desc())
        )
    ).scalars().all()
    return [PendingVendorResponse.model_validate(row) for row in rows]


async def _dismiss_pending_matching_masters(db: AsyncSession, org_id: int) -> None:
    """Remove queue rows when the vendor is already registered in masters."""
    from app.services.vendor_detection import find_matching_vendor_master

    masters = await list_vendor_masters(db, org_id)
    pending = (
        await db.execute(
            select(PendingVendor).where(
                PendingVendor.org_id == org_id,
                PendingVendor.status == "pending",
            )
        )
    ).scalars().all()
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
    org_id: int,
    body: PendingVendorCreate,
) -> PendingVendorResponse:
    from app.services.vendor_detection import find_matching_vendor_master

    masters = await list_vendor_masters(db, org_id)
    if find_matching_vendor_master(body.detected_name, body.detected_abn, masters):
        raise ValueError("Vendor already registered in master data")

    existing = (
        await db.execute(
            select(PendingVendor).where(
                PendingVendor.org_id == org_id,
                PendingVendor.status == "pending",
            )
        )
    ).scalars().all()
    name_key = body.detected_name.strip().lower()
    for row in existing:
        if row.detected_name.strip().lower() == name_key:
            return PendingVendorResponse.model_validate(row)

    row = PendingVendor(
        org_id=org_id,
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


async def dismiss_pending_vendor(db: AsyncSession, org_id: int, pending_id: int) -> None:
    row = await db.get(PendingVendor, pending_id)
    if not row or row.org_id != org_id:
        raise LookupError("Pending vendor not found")
    row.status = "dismissed"
    row.resolved_at = datetime.now(UTC)
    await db.flush()


async def promote_pending_vendor(
    db: AsyncSession,
    org_id: int,
    pending_id: int,
    body: PendingVendorPromote,
) -> VendorMasterResponse:
    row = await db.get(PendingVendor, pending_id)
    if not row or row.org_id != org_id or row.status != "pending":
        raise LookupError("Pending vendor not found")

    from app.services.vendor_detection import find_matching_vendor_master

    masters = await list_vendor_masters(db, org_id)
    existing = find_matching_vendor_master(row.detected_name, row.detected_abn, masters)
    if existing is not None:
        row.status = "promoted"
        row.promoted_master_id = existing.id
        row.resolved_at = datetime.now(UTC)
        await db.flush()
        from app.services.vendor_hold_service import release_invoices_after_vendor_promotion

        await release_invoices_after_vendor_promotion(
            db,
            org_id,
            vendor_name=existing.name,
            source_invoice_id=row.source_invoice_id,
        )
        return existing

    name = body.name or row.detected_name
    master_id = body.master_id or _new_master_id("vm", name)
    vendor = await create_vendor_master(
        db,
        org_id,
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

    from app.services.vendor_hold_service import release_invoices_after_vendor_promotion

    await release_invoices_after_vendor_promotion(
        db,
        org_id,
        vendor_name=name,
        source_invoice_id=row.source_invoice_id,
    )
    return vendor


async def attach_masters_to_config_dict(
    db: AsyncSession,
    org_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Merge DB masters into a rule book config dict for API responses."""
    vendors = await list_vendor_masters(db, org_id)
    employees = await list_employee_masters(db, org_id)
    merged = dict(data)
    merged["vendor_masters"] = [vendor_master_to_dict(v) for v in vendors]
    merged["employee_masters"] = [employee_master_to_dict(e) for e in employees]
    return merged
