import os

os.environ.setdefault("AUTH_REQUIRED", "false")

from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.main import app

get_settings.cache_clear()
from app.models.audit import AuditLog
from app.models.organisation import Organisation
from app.models.user_org_membership import UserOrgMembership
from app.services.invoice_data import InvoiceData, ParsedLineItem

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    AuditLog.__table__.c.detail.type = JSON()
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Organisation(id=1, name="High Volt Analytics", slug="hv-org")
        )
        await session.flush()
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session
        await db_session.commit()

    app.dependency_overrides[get_db] = override_get_db
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
    )


@pytest.fixture
def valid_abns() -> list[str]:
    return ["51824753556", "53004085616", "83914571673"]


@pytest.fixture
def invalid_abns() -> list[str]:
    return ["12345678901", "00000000000", "123"]
