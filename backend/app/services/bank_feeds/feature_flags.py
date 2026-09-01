"""Bank feeds feature gates (unsigned / pending design review).

Transfer was scoped out of Phase 6 until cross-account verification is designed.
Keep disabled in production until explicitly enabled after review.
"""

from __future__ import annotations

import os

_DEFAULT_TRANSFER_ENABLED = False


def bank_feeds_transfer_enabled() -> bool:
    raw = os.getenv("BANK_FEEDS_TRANSFER_ENABLED", "")
    if raw.strip():
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return _DEFAULT_TRANSFER_ENABLED
