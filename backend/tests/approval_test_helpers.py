"""Patches for approval API tests (stored file checks)."""

from __future__ import annotations

import pytest


def patch_approval_file_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat any non-empty raw_file_path as available; skip blob repair side effects."""

    monkeypatch.setattr(
        "app.services.shared.file_storage.stored_file_available",
        lambda stored_path, **kwargs: bool(stored_path and str(stored_path).strip()),
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service.stored_file_available",
        lambda stored_path, **kwargs: bool(stored_path and str(stored_path).strip()),
    )

    async def _noop_repair(_session, _inv) -> bool:
        return False

    monkeypatch.setattr(
        "app.services.shared.file_storage.repair_invoice_stored_path",
        _noop_repair,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service.repair_invoice_stored_path",
        _noop_repair,
    )
