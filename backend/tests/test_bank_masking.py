"""API-layer bank identifier masking (ISO 27001 A.8.11)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.user import UserRole
from app.models.vendor_master import VendorMasterRecord
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
from app.services.shared.bank_masking import (
    looks_masked,
    mask_account,
    mask_bsb,
    mask_iban,
    merge_bank_update,
)
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers

FULL_ACCOUNT = "12345678"
FULL_BSB = "062-000"
FULL_IBAN = "GB82WEST12345698765432"


def test_mask_account_keeps_last_four() -> None:
    assert mask_account(FULL_ACCOUNT) == "••••5678"
    assert mask_account("••••5678") == "••••5678"
    assert looks_masked("••••5678")
    assert not looks_masked(FULL_ACCOUNT)


def test_mask_bsb_keeps_last_three() -> None:
    assert mask_bsb(FULL_BSB) == "••••000"


def test_mask_iban_keeps_country_and_last_four() -> None:
    masked = mask_iban(FULL_IBAN)
    assert masked.startswith("GB")
    assert masked.endswith("5432")
    assert "WEST" not in masked
    assert looks_masked(masked)


def test_looks_masked_does_not_treat_iban_letters_as_mask() -> None:
    assert not looks_masked(FULL_IBAN)
    assert looks_masked("****1234")
    assert looks_masked("****5678")


def test_merge_bank_update_ignores_masked_echo() -> None:
    existing = {
        "account_number": FULL_ACCOUNT,
        "bsb": FULL_BSB,
        "iban": FULL_IBAN,
        "account_name": "Acme Pty Ltd",
    }
    merged = merge_bank_update(
        existing,
        {
            "account_number": mask_account(FULL_ACCOUNT),
            "bsb": mask_bsb(FULL_BSB),
            "iban": mask_iban(FULL_IBAN),
            "account_name": "Acme Pty Ltd",
        },
    )
    assert merged["account_number"] == FULL_ACCOUNT
    assert merged["bsb"] == FULL_BSB
    assert merged["iban"] == FULL_IBAN


@pytest.mark.asyncio
async def test_vendor_master_api_masks_bank_by_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    clear_classification_config_cache()
    res = await client.post(
        "/api/vendor-masters",
        json={
            "name": "Masked Bank Vendor",
            "status": "Active",
            "bank": {
                "account_number": FULL_ACCOUNT,
                "bsb": FULL_BSB,
                "iban": FULL_IBAN,
                "account_name": "Masked Bank Vendor",
                "bank_name": "CBA",
            },
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()["data"]
    master_id = created["id"]
    assert created["bank_masked"] is True
    assert created["bank"]["account_number"] == mask_account(FULL_ACCOUNT)
    assert created["bank"]["bsb"] == mask_bsb(FULL_BSB)
    assert created["bank"]["iban"] == mask_iban(FULL_IBAN)

    listed = await client.get("/api/vendor-masters")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["data"] if item["id"] == master_id)
    assert row["bank"]["account_number"] == mask_account(FULL_ACCOUNT)
    assert FULL_ACCOUNT not in listed.text

    stored = (
        await db_session.execute(
            select(VendorMasterRecord).where(
                VendorMasterRecord.tenant_id == TESTING_TENANT_UUID,
                VendorMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one()
    assert stored.bank["account_number"] == FULL_ACCOUNT
    assert stored.bank["bsb"] == FULL_BSB
    assert stored.bank["iban"] == FULL_IBAN

    revealed = await client.get("/api/vendor-masters?reveal_bank=true")
    assert revealed.status_code == 200
    revealed_row = next(item for item in revealed.json()["data"] if item["id"] == master_id)
    assert revealed_row["bank_masked"] is False
    assert revealed_row["bank"]["account_number"] == FULL_ACCOUNT
    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.event == "bank_details_revealed")
        )
    ).scalars().all()
    assert "bank_details_revealed" in events

    patched = await client.patch(
        f"/api/vendor-masters/{master_id}",
        json={
            "bank": {
                "account_number": mask_account(FULL_ACCOUNT),
                "account_name": "Renamed Account",
            }
        },
    )
    assert patched.status_code == 200, patched.text
    await db_session.refresh(stored)
    assert stored.bank["account_number"] == FULL_ACCOUNT
    assert stored.bank["account_name"] == "Renamed Account"

    await client.delete(f"/api/vendor-masters/{master_id}")


@pytest.mark.asyncio
async def test_non_finance_role_cannot_reveal_bank(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await seed_admin_user(
        db_session,
        email="member-bank@test.example.com",
        role=UserRole.MEMBER,
    )
    await db_session.commit()
    headers = tenant_auth_headers(token, TESTING_TENANT_UUID)
    res = await client.get("/api/vendor-masters?reveal_bank=true", headers=headers)
    assert res.status_code == 403

    perms = await client.get("/api/auth/me/permissions", headers=headers)
    assert perms.status_code == 200
    assert perms.json()["data"]["can_reveal_bank"] is False

    admin_perms = await client.get("/api/auth/me/permissions")
    assert admin_perms.status_code == 200
    assert admin_perms.json()["data"]["can_reveal_bank"] is True


@pytest.mark.asyncio
async def test_invoice_get_masks_bank_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-BANK-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="bankhash1",
        bank_bsb=FULL_BSB,
        bank_account=FULL_ACCOUNT,
        extracted_fields={"bank_account": FULL_ACCOUNT, "bank_bsb": FULL_BSB},
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get(f"/api/invoices/{inv.id}")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["bank_masked"] is True
    assert data["bank_account"] == mask_account(FULL_ACCOUNT)
    assert data["bank_bsb"] == mask_bsb(FULL_BSB)
    assert data["extracted_fields"]["bank_account"] == mask_account(FULL_ACCOUNT)
    assert FULL_ACCOUNT not in res.text

    revealed = await client.get(f"/api/invoices/{inv.id}?reveal_bank=true")
    assert revealed.status_code == 200
    revealed_data = revealed.json()["data"]
    assert revealed_data["bank_masked"] is False
    assert revealed_data["bank_account"] == FULL_ACCOUNT
    assert revealed_data["extracted_fields"]["bank_account"] == FULL_ACCOUNT
