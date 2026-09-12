"""Without-document / manual-entry claims may be approved without a stored blob."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.invoice.processing_override_catalog import (
    allows_approval_without_stored_file,
    has_skip_extraction,
)
from app.services.shared.file_storage import ensure_invoice_stored_file


def test_without_document_flag_allows_approval_without_file() -> None:
    inv = SimpleNamespace(
        processing_overrides=None,
        extracted_fields={"without_document": "true", "manual_entry": "true"},
    )
    assert has_skip_extraction(inv) is True  # type: ignore[arg-type]
    assert allows_approval_without_stored_file(inv) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ensure_stored_file_skips_without_document() -> None:
    inv = SimpleNamespace(
        id=99,
        tenant_id=None,
        raw_file_path=None,
        processing_overrides={"skip_extraction": True},
        extracted_fields={"without_document": "true"},
    )
    session = MagicMock()
    with patch(
        "app.services.shared.file_storage.repair_invoice_stored_path",
        new_callable=AsyncMock,
    ) as repair:
        await ensure_invoice_stored_file(session, inv)
        repair.assert_not_awaited()
