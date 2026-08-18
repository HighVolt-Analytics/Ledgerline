"""Master data self-confirmation email flow."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.master_data import EmployeeMasterCreate, VendorMasterCreate
from app.services.auth.auth_email_service import InviteEmailResult
from app.services.master_data.master_confirmation_service import (
    preview_master_confirmation,
    save_master_confirmation,
    send_master_confirmation,
)
from app.services.master_data.master_data_service import (
    create_employee_master,
    create_vendor_master,
    get_employee_master_by_id,
    get_vendor_master_by_id,
    update_employee_master,
    update_vendor_master,
)
from app.schemas.master_data import EmployeeMasterUpdate, VendorMasterUpdate
from app.services.purchase.team_expense_validator import find_employee_by_sender
from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import BankDetails, EmployeeBudget
from tests.auth_test_helpers import seed_admin_user
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _public_app_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:8001")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_confirmation_email(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    async def _ok(**kwargs):
        captured.append(kwargs)
        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.master_data.master_confirmation_service.send_master_confirmation_email",
        _ok,
    )
    return captured


async def _seed_admin(db_session: AsyncSession) -> str:
    _, token = await seed_admin_user(
        db_session,
        email="admin@master-confirm.example.com",
        tenant_slug="hv-org",
        full_name="Master Confirm Admin",
    )
    await db_session.commit()
    return token


@pytest.mark.asyncio
async def test_send_vendor_confirmation_requires_contact_email(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    vendor = await create_vendor_master(
        db_session,
        TESTING_TENANT_UUID,
        VendorMasterCreate(name="Acme Supplies", contact_email=""),
    )
    await db_session.commit()

    result = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="vendor",
        master_id=vendor.id,
    )
    assert not result.sent
    assert "Contact email" in (result.error or "")


@pytest.mark.asyncio
async def test_vendor_save_via_token_updates_master_and_sets_active(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    vendor = await create_vendor_master(
        db_session,
        TESTING_TENANT_UUID,
        VendorMasterCreate(
            name="Acme Supplies",
            contact_email="accounts@acme.example.com",
            default_ledger="Trade Creditors",
        ),
    )
    await db_session.commit()

    send = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="vendor",
        master_id=vendor.id,
    )
    assert send.sent
    await db_session.commit()

    # Extract raw token from the mocked send call by creating a fresh send and reading DB hash is hard;
    # instead create token via service and capture from DB by invalidating and re-sending with known token.
    from app.models.master_confirmation_token import MasterConfirmationToken
    from sqlalchemy import select

    token_row = (
        await db_session.execute(
            select(MasterConfirmationToken).where(
                MasterConfirmationToken.master_id == vendor.id,
                MasterConfirmationToken.kind == "vendor",
            )
        )
    ).scalar_one()

    import hashlib
    import secrets

    raw_token = secrets.token_urlsafe(32)
    token_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    preview = await preview_master_confirmation(db_session, token=raw_token)
    assert preview.kind == "vendor"
    assert preview.fields["name"] == "Acme Supplies"

    saved = await save_master_confirmation(
        db_session,
        token=raw_token,
        fields={
            "name": "Acme Supplies Pty Ltd",
            "contact_email": "billing@acme.example.com",
            "aliases": ["Acme"],
            "abn": "51824753556",
            "payment_terms": "Net 30",
            "billing_address": {
                "street": "1 Main St",
                "suburb": "Sydney",
                "postcode": "2000",
                "country": "AU",
            },
            "bank": {
                "bsb": "062000",
                "account_number": "12345678",
                "account_name": "Acme Supplies",
                "bank_name": "CBA",
            },
            "default_ledger": "Should Not Stick",
            "status": "Should Not Stick",
        },
    )
    await db_session.commit()

    assert saved.status == "Active"
    row = await get_vendor_master_by_id(db_session, TESTING_TENANT_UUID, vendor.id)
    assert row is not None
    assert row.name == "Acme Supplies Pty Ltd"
    assert row.contact_email == "billing@acme.example.com"
    assert row.default_ledger == "Trade Creditors"
    assert row.status == "Active"
    assert row.confirmed_at is not None


@pytest.mark.asyncio
async def test_employee_save_rejects_duplicate_email(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    first = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(name="Alex Tan", email="alex@acme.example.com"),
    )
    second = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(name="Priya Sharma", email="priya@acme.example.com"),
    )
    await db_session.commit()

    send = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="employee",
        master_id=second.id,
    )
    assert send.sent

    from app.models.master_confirmation_token import MasterConfirmationToken
    from sqlalchemy import select
    import hashlib
    import secrets

    token_row = (
        await db_session.execute(
            select(MasterConfirmationToken).where(
                MasterConfirmationToken.master_id == second.id,
                MasterConfirmationToken.kind == "employee",
            )
        )
    ).scalar_one()
    raw_token = secrets.token_urlsafe(32)
    token_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    with pytest.raises(Exception) as exc:
        await save_master_confirmation(
            db_session,
            token=raw_token,
            fields={
                "name": "Priya Sharma",
                "email": "alex@acme.example.com",
                "whatsapp_number": "",
                "whatsapp_number_2": "",
                "viber_number": "",
                "date_of_joining": "",
                "department": "Sales",
                "role": "Rep",
                "location": "",
                "division": "",
                "supervisor_1": "",
                "supervisor_2": "",
                "bank": {
                    "bsb": "",
                    "account_number": "99999999",
                    "account_name": "Priya Sharma",
                    "bank_name": "CBA",
                },
            },
        )
    assert "already uses this email" in str(exc.value)


@pytest.mark.asyncio
async def test_employee_save_updates_match_email(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            name="Priya Sharma",
            email="priya@acme.example.com",
            department="Sales",
        ),
    )
    await db_session.commit()

    send = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="employee",
        master_id=employee.id,
    )
    assert send.sent

    from app.models.master_confirmation_token import MasterConfirmationToken
    from sqlalchemy import select
    import hashlib
    import secrets

    token_row = (
        await db_session.execute(
            select(MasterConfirmationToken).where(
                MasterConfirmationToken.master_id == employee.id,
                MasterConfirmationToken.kind == "employee",
            )
        )
    ).scalar_one()
    raw_token = secrets.token_urlsafe(32)
    token_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    await save_master_confirmation(
        db_session,
        token=raw_token,
        fields={
            "name": "Priya Sharma",
            "email": "priya.new@acme.example.com",
            "whatsapp_number": "+61400111222",
            "whatsapp_number_2": "",
            "viber_number": "",
            "date_of_joining": "2024-01-01",
            "department": "Marketing",
            "role": "Manager",
            "location": "Sydney",
            "division": "",
            "supervisor_1": "",
            "supervisor_2": "",
            "bank": {
                "bsb": "062000",
                "account_number": "12345678",
                "account_name": "Priya Sharma",
                "bank_name": "CBA",
            },
        },
    )
    await db_session.commit()

    row = await get_employee_master_by_id(db_session, TESTING_TENANT_UUID, employee.id)
    assert row is not None
    assert row.email == "priya.new@acme.example.com"
    assert row.department == "Marketing"
    assert row.status == "Active"

    schema = EmployeeMasterResponse(
        id=row.master_id,
        name=row.name,
        email=row.email,
        whatsapp_number=row.whatsapp_number,
        bank=BankDetails(**(row.bank or {})),
        budget=EmployeeBudget(**(row.spending_limits or {})),
        status=row.status,
        db_id=row.id,
    )
    matched = find_employee_by_sender([schema], "priya.new@acme.example.com")
    assert matched is not None
    assert matched.name == "Priya Sharma"


@pytest.mark.asyncio
async def test_admin_ledger_only_update_does_not_resend(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    vendor = await create_vendor_master(
        db_session,
        TESTING_TENANT_UUID,
        VendorMasterCreate(name="Ledger Only Vendor", contact_email="pay@vendor.example.com"),
    )
    await db_session.commit()

    from app.services.master_data.master_confirmation_service import maybe_send_after_admin_change

    result = await maybe_send_after_admin_change(
        db_session,
        TESTING_TENANT_UUID,
        kind="vendor",
        master_id=vendor.id,
        confirmable_changed=False,
    )
    assert result is None

    await update_vendor_master(
        db_session,
        TESTING_TENANT_UUID,
        vendor.id,
        VendorMasterUpdate(default_ledger="Office Expenses"),
    )
    await db_session.commit()

    row = await get_vendor_master_by_id(db_session, TESTING_TENANT_UUID, vendor.id)
    assert row is not None
    assert row.default_ledger == "Office Expenses"


@pytest.mark.asyncio
async def test_public_preview_and_save_api(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    admin_token = await _seed_admin(db_session)
    create_res = await client.post(
        "/api/employee-masters",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Sam Lee",
            "email": "sam@acme.example.com",
            "status": "Pending verification",
        },
    )
    assert create_res.status_code == 201
    master_id = create_res.json()["data"]["id"]

    from app.models.master_confirmation_token import MasterConfirmationToken
    from sqlalchemy import select
    import hashlib
    import secrets

    token_row = (
        await db_session.execute(
            select(MasterConfirmationToken).where(
                MasterConfirmationToken.master_id == master_id,
                MasterConfirmationToken.kind == "employee",
            )
        )
    ).scalar_one()
    raw_token = secrets.token_urlsafe(32)
    token_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    preview_res = await client.get(f"/api/master-confirm/preview?token={raw_token}")
    assert preview_res.status_code == 200
    preview = preview_res.json()["data"]
    assert preview["kind"] == "employee"
    assert preview["fields"]["name"] == "Sam Lee"

    save_res = await client.post(
        "/api/master-confirm/save",
        json={
            "token": raw_token,
            "fields": {
                **preview["fields"],
                "department": "Ops",
            },
        },
    )
    assert save_res.status_code == 200
    assert save_res.json()["data"]["status"] == "Active"

    reuse = await client.post(
        "/api/master-confirm/save",
        json={"token": raw_token, "fields": preview["fields"]},
    )
    assert reuse.status_code == 410


@pytest.mark.asyncio
async def test_confirm_master_page_is_public_html(client: AsyncClient) -> None:
    res = await client.get("/confirm-master")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "Confirm your details" in res.text
    assert "Save and confirm" in res.text


def test_confirm_master_paths_skip_tenant_default() -> None:
    from app.tenant_isolation.resolution import TenantResolutionService

    assert TenantResolutionService.should_skip_default("/confirm-master")
    assert TenantResolutionService.should_skip_default("/api/master-confirm/preview")
    assert TenantResolutionService.should_skip_default("/api/master-confirm/save")


@pytest.mark.asyncio
async def test_send_confirmation_email_link_is_standalone_page(
    db_session: AsyncSession,
    mock_confirmation_email: list[dict],
) -> None:
    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(name="Link Check", email="link@acme.example.com"),
    )
    await db_session.commit()
    send = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="employee",
        master_id=employee.id,
    )
    assert send.sent
    assert mock_confirmation_email
    confirm_url = mock_confirmation_email[-1]["confirm_url"]
    assert "/confirm-master?token=" in confirm_url
    assert "/login" not in confirm_url


@pytest.mark.asyncio
async def test_save_ignores_foreign_master_id_and_stays_on_token_tenant(
    db_session: AsyncSession,
    mock_confirmation_email,
) -> None:
    import uuid

    from app.models.master_confirmation_token import MasterConfirmationToken
    from app.models.tenant import Tenant
    from sqlalchemy import select
    import hashlib
    import secrets

    own = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(name="Own Employee", email="own@acme.example.com", department="Sales"),
    )
    other_tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=other_tenant_id, name="Other Org", slug=f"other-{other_tenant_id.hex[:8]}"))
    await db_session.flush()
    other = await create_employee_master(
        db_session,
        other_tenant_id,
        EmployeeMasterCreate(name="Other Employee", email="other@acme.example.com", department="Finance"),
    )
    await db_session.commit()

    send = await send_master_confirmation(
        db_session,
        TESTING_TENANT_UUID,
        kind="employee",
        master_id=own.id,
    )
    assert send.sent

    token_row = (
        await db_session.execute(
            select(MasterConfirmationToken).where(
                MasterConfirmationToken.master_id == own.id,
                MasterConfirmationToken.kind == "employee",
            )
        )
    ).scalar_one()
    raw_token = secrets.token_urlsafe(32)
    token_row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    await db_session.commit()

    saved = await save_master_confirmation(
        db_session,
        token=raw_token,
        fields={
            "name": "Own Employee",
            "email": "own@acme.example.com",
            "department": "Marketing",
            "role": "",
            "whatsapp_number": "",
            "whatsapp_number_2": "",
            "viber_number": "",
            "date_of_joining": "",
            "location": "",
            "division": "",
            "supervisor_1": "",
            "supervisor_2": "",
            "bank": {
                "bsb": "",
                "account_number": "",
                "account_name": "",
                "bank_name": "",
            },
            "master_id": other.id,
            "advance_parent_ledger": "Should Not Stick",
        },
    )
    await db_session.commit()
    assert saved.master_id == own.id
    assert saved.status == "Active"

    own_row = await get_employee_master_by_id(db_session, TESTING_TENANT_UUID, own.id)
    other_row = await get_employee_master_by_id(db_session, other_tenant_id, other.id)
    assert own_row is not None
    assert own_row.department == "Marketing"
    assert other_row is not None
    assert other_row.department == "Finance"
    assert other_row.name == "Other Employee"
