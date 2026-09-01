"""Shared CFO efficiency & automation benchmark assumptions.

Headline CFO cards use one consolidated manual baseline (minutes and cost per
invoice). Channel-level baselines in ``dashboard_savings`` remain for the
legacy dashboard capture-source panel only.
"""

from __future__ import annotations

from decimal import Decimal

# Touchless / STP target — not yet tenant-configurable (Process Efficiency shows "-").
TOUCHLESS_TARGET_PCT = Decimal("85")

# Manual AP processing benchmark for CFO headline cards (cost + time saved).
MANUAL_COST_PER_INVOICE_BASELINE = Decimal("30.00")
MANUAL_PROCESSING_MINUTES_BASELINE = Decimal("182")

# FTE equivalent for hours-saved YTD (1,830 ≈ 220 working days × 8.32 hrs).
FTE_HOURS_PER_YEAR = Decimal("1830")

# Document retention policy window (days) — not yet tenant-configurable.
DOCUMENT_RETENTION_DAYS = 2555  # ~7 years

# Accounting sync jobs exhausted retries are treated as dead-letter items.
SYNC_DEAD_LETTER_MIN_ATTEMPTS = 5
