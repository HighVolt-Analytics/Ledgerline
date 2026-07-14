"""Layer 3 — probable vendor-master duplicates (report-only, no auto-merge)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor_master import VendorMasterRecord
from app.services.master_data.vendor_duplicate_report import find_probable_duplicate_vendors
from app.tenant_ids import TESTING_TENANT_UUID


async def _add_master(
    session: AsyncSession,
    *,
    master_id: str,
    name: str,
    abn: str = "",
    billing_address: dict | None = None,
) -> VendorMasterRecord:
    row = VendorMasterRecord(
        tenant_id=TESTING_TENANT_UUID,
        master_id=master_id,
        name=name,
        aliases=[],
        abn=abn,
        billing_address=billing_address or {},
        bank={},
        status="active",
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_probable_duplicates_3b_semiconductors(db_session: AsyncSession) -> None:
    await _add_master(
        db_session,
        master_id="vm-3b-a",
        name="3B Semiconductors Pvt. Ltd.",
    )
    await _add_master(
        db_session,
        master_id="vm-3b-b",
        name="3B SEMICONDUCTORS PRIVATE LIMITED",
    )
    await _add_master(
        db_session,
        master_id="vm-other",
        name="Completely Different Co",
    )

    pairs = await find_probable_duplicate_vendors(db_session, tenant_id=TESTING_TENANT_UUID)
    assert len(pairs) >= 1
    hit = next(p for p in pairs if {p.left_master_id, p.right_master_id} == {"vm-3b-a", "vm-3b-b"})
    assert "name_similarity" in hit.reasons
    assert hit.score >= 0.88
    assert all(
        {p.left_master_id, p.right_master_id} != {"vm-3b-a", "vm-other"}
        and {p.left_master_id, p.right_master_id} != {"vm-3b-b", "vm-other"}
        for p in pairs
    )


@pytest.mark.asyncio
async def test_probable_duplicates_shared_abn(db_session: AsyncSession) -> None:
    await _add_master(db_session, master_id="vm-abn-1", name="Alpha Trading", abn="51824753556")
    await _add_master(db_session, master_id="vm-abn-2", name="Alpha Trading Pty", abn="51 824 753 556")

    pairs = await find_probable_duplicate_vendors(db_session, tenant_id=TESTING_TENANT_UUID)
    hit = next(p for p in pairs if {p.left_master_id, p.right_master_id} == {"vm-abn-1", "vm-abn-2"})
    assert "shared_abn" in hit.reasons


@pytest.mark.asyncio
async def test_probable_duplicates_shared_address(db_session: AsyncSession) -> None:
    addr = {"street": "1 Test St", "suburb": "Sydney", "postcode": "2000", "country": "AU"}
    await _add_master(db_session, master_id="vm-addr-1", name="Beta Supplies", billing_address=addr)
    await _add_master(db_session, master_id="vm-addr-2", name="Beta Supplies Group", billing_address=addr)

    pairs = await find_probable_duplicate_vendors(db_session, tenant_id=TESTING_TENANT_UUID)
    hit = next(p for p in pairs if {p.left_master_id, p.right_master_id} == {"vm-addr-1", "vm-addr-2"})
    assert "shared_address" in hit.reasons or "name_similarity" in hit.reasons
