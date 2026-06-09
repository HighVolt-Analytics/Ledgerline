"""Phase B: vendor hold, employee master enforcement, team approval policy."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_vendor import PendingVendor
from app.schemas.master_data import PendingVendorPromote, VendorMasterCreate
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.approval_service import approve_invoice_for_reprocess
from app.services.capture_channel import channel_rule_matches, infer_capture_channel
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice_evaluation_service import EVAL_PENDING_VENDOR, ROUTE_TEAM
from app.services.master_data_service import promote_pending_vendor
from app.services.team_expense_approval import team_expense_auto_approve_eligible
from app.services.team_expense_validator import (
    _find_employee_by_sender,
    run_team_expense_validations,
    vr_te04_bank,
    vr_te05_status,
)
from app.services.validator import ValidationResult
from app.services.vendor_hold_service import apply_vendor_hold_if_needed, invoice_is_vendor_held
from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import BankDetails, EmployeeBudget


@pytest.fixture
def capture_config() -> RuleBookConfigPayload:
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    return validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))


def test_infer_capture_channel() -> None:
    assert infer_capture_channel("ops@acme.com") == "email"
    assert infer_capture_channel("+61 412 345 678") == "mob"
    assert channel_rule_matches("Any", "email")
    assert channel_rule_matches("Email", "email")
    assert not channel_rule_matches("Email", "mob")


def test_find_employee_by_whatsapp() -> None:
    employee = EmployeeMasterResponse(
        id="em-1",
        name="Marcus Webb",
        email="",
        whatsapp_number="+61 412 345 678",
        bank=BankDetails(),
        budget=EmployeeBudget(),
        status="Active",
        db_id=1,
    )
    match = _find_employee_by_sender([employee], "+61 412 345 678")
    assert match is not None
    assert match.name == "Marcus Webb"


def test_vr_te04_bank_required() -> None:
    employee = EmployeeMasterResponse(
        id="em-1",
        name="Alex Tan",
        email="alex@acme.com",
        bank=BankDetails(),
        budget=EmployeeBudget(),
        status="Active",
        db_id=1,
    )
    result = vr_te04_bank(employee)
    assert not result.passed


def test_vr_te05_pending_verification_blocks() -> None:
    employee = EmployeeMasterResponse(
        id="em-1",
        name="Alex Tan",
        email="alex@acme.com",
        bank=BankDetails(account_number="12345678"),
        budget=EmployeeBudget(),
        status="Pending verification",
        db_id=1,
    )
    result = vr_te05_status(employee)
    assert not result.passed


def test_team_auto_approve_waives_receipt_only(capture_config: RuleBookConfigPayload) -> None:
    from app.schemas.rule_book_config import TeamExpensePolicy

    team_rule = capture_config.team_expense_rules[0]
    team_rule = team_rule.model_copy(
        update={"policy": TeamExpensePolicy(auto_approve_below=30, require_receipt=True)}
    )
    results = [
        ValidationResult("VR01", True, "ok"),
        ValidationResult("VR-TE03", False, "Receipt required"),
    ]
    assert team_expense_auto_approve_eligible(
        results,
        route_target=ROUTE_TEAM,
        amount=25.0,
        team_rule=team_rule,
    )


@pytest.mark.asyncio
async def test_vendor_hold_blocks_processing(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown Supplier Pty Ltd",
        status=InvoiceStatus.VALIDATING,
        evaluation_status=EVAL_PENDING_VENDOR,
        currency="AUD",
        file_hash="hold-1",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held
    assert inv.status == InvoiceStatus.EXCEPTION
    assert await invoice_is_vendor_held(db_session, inv)


@pytest.mark.asyncio
async def test_promote_pending_vendor_releases_held_invoice(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = tmp_path / "uploads"
    rule_books = upload / "rule_books"
    rule_books.mkdir(parents=True)
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    shutil.copy2(template, rule_books / "1_config.json")
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    get_settings.cache_clear()
    from app.services.rule_book_mapper import clear_classification_config_cache

    clear_classification_config_cache()
    inv = Invoice(
        org_id=1,
        vendor="New Vendor Co",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status=EVAL_PENDING_VENDOR,
        currency="AUD",
        file_hash="hold-release",
    )
    db_session.add(inv)
    await db_session.flush()

    pending = PendingVendor(
        org_id=1,
        detected_name="New Vendor Co",
        source_invoice_id=inv.id,
        confidence=42.0,
        status="pending",
    )
    db_session.add(pending)
    await db_session.flush()

    await promote_pending_vendor(
        db_session,
        1,
        pending.id,
        PendingVendorPromote(
            master_id="vm-new",
            name="New Vendor Co",
            default_ledger="Operating Expenses",
            status="Active",
        ),
    )
    await db_session.refresh(inv)

    assert inv.status == InvoiceStatus.PENDING


@pytest.mark.asyncio
async def test_quarterly_budget_validation(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            org_id=1,
            master_id="em-qtr",
            name="Ops Lead",
            email="ops@acme-hospitality.com.au",
            budget={"monthly": 5000.0, "quarterly": 100.0, "annual": 45000.0, "categories": []},
            mtd_spent=10.0,
            qtd_spent=90.0,
            ytd_spent=100.0,
            status="Active",
            bank={"account_number": "12345678"},
        )
    )
    await db_session.flush()

    data = InvoiceData(
        vendor="Cafe",
        total=Decimal("20.00"),
        line_items=[ParsedLineItem(description="team lunch meal", amount=Decimal("20.00"))],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        org_id=1,
        route_target=ROUTE_TEAM,
        email_sender="ops@acme-hospitality.com.au",
        config=capture_config,
    )
    by_rule = {row.rule: row for row in results}
    assert not by_rule["VR-TE02"].passed
    assert "quarterly" in by_rule["VR-TE02"].message.lower()
