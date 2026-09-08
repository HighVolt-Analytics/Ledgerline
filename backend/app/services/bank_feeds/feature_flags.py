"""Bank feeds feature gates.

Inter-account Transfer is enabled by default (Xero-style Match / Create / Transfer / Discuss).
Set BANK_FEEDS_TRANSFER_ENABLED=0 to disable.
"""

from __future__ import annotations

import os

_DEFAULT_TRANSFER_ENABLED = True


def bank_feeds_transfer_enabled() -> bool:
    raw = os.getenv("BANK_FEEDS_TRANSFER_ENABLED", "")
    if raw.strip():
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return _DEFAULT_TRANSFER_ENABLED
