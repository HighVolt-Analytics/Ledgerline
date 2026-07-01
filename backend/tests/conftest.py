import json
import os
from pathlib import Path

# Force auth off for API tests (local .env often sets AUTH_REQUIRED=true).
os.environ["AUTH_REQUIRED"] = "false"
os.environ["DEFAULT_TENANT_SLUG"] = "hv-org"
os.environ["DEFAULT_TENANT_NAME"] = "High Volt Analytics"
# Prevent local ngrok/tunnel URLs from breaking URL builder tests.
os.environ.pop("PUBLIC_TUNNEL_URL", None)
os.environ.pop("NGROK_URL", None)

from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base, get_db, get_preauth_db
from tests.legacy_tenant_support import install_legacy_tenant_coercion

install_legacy_tenant_coercion()
from app.main import app

get_settings.cache_clear()
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.tenant_ids import TESTING_TENANT_UUID
from app.services.invoice_data import InvoiceData, ParsedLineItem

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def capture_config():
    from tests.rule_book_fixtures import load_capture_config

    return load_capture_config()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    AuditLog.__table__.c.detail.type = JSON()
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    fixture = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    demo_config = json.loads(fixture.read_text(encoding="utf-8"))
    demo_config.pop("vendor_masters", None)
    demo_config.pop("employee_masters", None)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Tenant(
                id=TESTING_TENANT_UUID,
                name="High Volt Analytics",
                slug="hv-org",
            )
        )
        session.add(
            TenantRuleBookConfig(
                tenant_id=TESTING_TENANT_UUID,
                config=demo_config,
                schema_version=int(demo_config.get("schema_version") or 1),
            )
        )
        await session.flush()
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _disable_auth_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("DEFAULT_TENANT_SLUG", "hv-org")
    monkeypatch.setenv("DEFAULT_TENANT_NAME", "High Volt Analytics")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.setenv("AZURE_WEBAPP_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _use_demo_rule_book_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Tests use demo fixture; production template stays empty for real data."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    upload = tmp_path_factory.mktemp("uploads")
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(fixture))
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    monkeypatch.setenv("RULE_BOOK_SAVE_DEBOUNCE_MS", "0")
    get_settings.cache_clear()
    from app.services.account_mapper import clear_rule_book_cache
    from app.services.document_type_catalog import clear_document_type_catalog_cache
    from app.services.rule_book_mapper import clear_classification_config_cache
    from app.services.rule_book_save_buffer import clear_rule_book_save_buffers

    clear_rule_book_cache()
    clear_document_type_catalog_cache()
    clear_classification_config_cache()
    clear_rule_book_save_buffers()
    yield
    clear_rule_book_save_buffers()
    clear_classification_config_cache()
    clear_document_type_catalog_cache()
    clear_rule_book_cache()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    get_settings.cache_clear()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session
        await db_session.commit()

    async def override_get_preauth_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session
        await db_session.commit()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_preauth_db] = override_get_preauth_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def sample_invoice_data() -> InvoiceData:
    return InvoiceData(
        vendor="Acme Pty Ltd",
        abn="51824753556",
        invoice_no="INV-TEST-001",
        invoice_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        currency="AUD",
        subtotal=Decimal("1000.00"),
        gst=Decimal("100.00"),
        total=Decimal("1100.00"),
        line_items=[
            ParsedLineItem(
                description="Consulting services",
                qty=Decimal("1"),
                unit_price=Decimal("1000.00"),
                amount=Decimal("1000.00"),
            )
        ],
        document_text="Tax Invoice for consulting services",
    )


@pytest.fixture
def valid_abns() -> list[str]:
    return ["51824753556", "53004085616", "83914571673"]


@pytest.fixture
def invalid_abns() -> list[str]:
    return ["12345678901", "00000000000", "123"]
