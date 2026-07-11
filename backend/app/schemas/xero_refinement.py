"""Supplementary Xero integration schemas (verify, mapping validation)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class XeroVerifyResponse(BaseModel):
    connected: bool
    needs_reauth: bool = False
    organisation_id: str | None = None
    organisation_name: str | None = None
    verified_at: datetime | None = None
    message: str | None = None
