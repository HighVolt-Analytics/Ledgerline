"""One-off: verify starter COA provisioning on signup + platform paths (local only)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.schemas.platform import CreatePlatformTenantRequest
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.auth.auth_service import hash_password
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.rule_book.account_mapper import AccountMapping, category_resolved_in_coa
from app.services.rule_book.rule_book_config_repository import fetch_config_dict
from app.services.rule_book.rule_book_mapper import ROUTE_SALES
from app.services.signup.signup_fulfillment_service import (
    ensure_pending_auth_account,
    fulfill_signup_tenant,
)
from app.services.signup.signup_session_service import SignupSession
from app.services.tenant.platform_service import create_client_tenant


def _check_journals(config, *, label: str) -> None:
    purchase = Invoice(
        tenant_id=uuid.uuid4(),
        invoice_date=date(2026, 7, 10),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        route_target="Purchase Management",
        currency="AUD",
    )
    sales = Invoice(
        tenant_id=uuid.uuid4(),
        invoice_date=date(2026, 7, 10),
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        route_target=ROUTE_SALES,
        currency="AUD",
    )
    purchase_unresolved = get_unresolved_control_accounts(invoice=purchase, config=config)
    sales_unresolved = get_unresolved_control_accounts(invoice=sales, config=config)
    purchase_lines = generate_entries(
        purchase,
        AccountMapping("6100", "Operating Expenses"),
        config=config,
    )
    sales_lines = generate_entries(
        sales,
        AccountMapping("4100", "Sales Revenue"),
        config=config,
    )
    print(f"  [{label}] COA accounts: {len(config.chart_of_accounts)}")
    print(f"  [{label}] posting_defaults.tax_account: {config.posting_defaults.tax_account!r}")
    print(f"  [{label}] purchase control unresolved: {purchase_unresolved}")
    print(f"  [{label}] sales control unresolved: {sales_unresolved}")
    print(f"  [{label}] purchase journal balanced: {is_balanced(purchase_lines)}")
    print(f"  [{label}] sales journal balanced: {is_balanced(sales_lines)}")
    assert not purchase_unresolved, purchase_unresolved
    assert not sales_unresolved, sales_unresolved
    assert is_balanced(purchase_lines)
    assert is_balanced(sales_lines)


async def _verify_signup_path(session) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    email = f"coa-verify-signup-{suffix}@example.com"
    password_hash = hash_password("VerifyOnly123!")
    account = await ensure_pending_auth_account(
        session, email=email, password_hash=password_hash
    )
    signup = SignupSession(
        session_id=f"verify-{suffix}",
        email=email,
        full_name="COA Verify Signup",
        provider="email",
        status="provisioning",
        organization_name=f"COA Verify Signup {suffix}",
        organization_slug=f"coa-verify-signup-{suffix}",
        country="AU",
        plan="free",
        password_hash=password_hash,
        auth_account_id=account.id,
    )
    tenant, user = await fulfill_signup_tenant(session, signup=signup)
    raw = await fetch_config_dict(session, tenant.id)
    assert raw is not None
    config = validate_rule_book_config_payload(raw)
    assert len(config.chart_of_accounts) == 8
    assert category_resolved_in_coa(config.posting_defaults.payable_account, config)
    assert category_resolved_in_coa(config.posting_defaults.tax_account, config)
    assert category_resolved_in_coa("Accounts Receivable", config)
    assert category_resolved_in_coa("Tax Collected", config)
    _check_journals(config, label="signup")
    print(f"  [signup] tenant_id={tenant.id} slug={tenant.slug} user={user.email}")
    return tenant.id


async def _verify_platform_path(session) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    body = CreatePlatformTenantRequest(
        name=f"COA Verify Platform {suffix}",
        slug=f"coa-verify-platform-{suffix}",
        country="GB",
        industry="Hospitality",
        first_admin_email=f"coa-verify-platform-{suffix}@example.com",
        first_admin_name="Platform Admin",
    )
    tenant_detail, _invite = await create_client_tenant(session, body, invited_by_user_id=None)
    tenant_id = tenant_detail.id
    raw = await fetch_config_dict(session, tenant_id)
    assert raw is not None
    config = validate_rule_book_config_payload(raw)
    assert config.posting_defaults.tax_account == "VAT Input"
    assert len(config.chart_of_accounts) == 8
    assert any(entry.name == "VAT Input" for entry in config.chart_of_accounts)
    _check_journals(config, label="platform")
    print(f"  [platform] tenant_id={tenant_id} slug={body.slug}")
    return tenant_id


async def main() -> None:
    async with async_session_factory() as session:
        print("=== Signup provisioning path (fulfill_signup_tenant) ===")
        signup_tid = await _verify_signup_path(session)
        print("=== Platform admin path (create_client_tenant) ===")
        platform_tid = await _verify_platform_path(session)
        await session.commit()
        print("=== OK: both paths seeded functional starter COA ===")
        print(f"signup tenant: {signup_tid}")
        print(f"platform tenant: {platform_tid}")


if __name__ == "__main__":
    asyncio.run(main())
