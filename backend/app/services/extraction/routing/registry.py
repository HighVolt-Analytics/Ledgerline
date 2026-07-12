"""Strategy registry: ExtractionRoute → DocumentExtractionStrategy."""

from __future__ import annotations

from app.services.extraction.routing.routes import (
    INVOICE_FAMILY_ROUTES,
    LAYOUT_ONLY_ROUTES,
    LAYOUT_PRIMARY_ROUTES,
    ExtractionRoute,
)
from app.services.extraction.routing.strategies import (
    InvoiceFamilyStrategy,
    LayoutOnlyReviewStrategy,
    LayoutPrimaryStrategy,
    ReceiptOrClaimStrategy,
)
from app.services.extraction.routing.strategy import DocumentExtractionStrategy


def get_extraction_strategy(route: ExtractionRoute) -> DocumentExtractionStrategy:
    if route in INVOICE_FAMILY_ROUTES:
        return InvoiceFamilyStrategy(route)
    if route in {ExtractionRoute.RECEIPT, ExtractionRoute.EXPENSE_CLAIM}:
        return ReceiptOrClaimStrategy(route)
    if route in LAYOUT_PRIMARY_ROUTES:
        return LayoutPrimaryStrategy(route)
    if route in LAYOUT_ONLY_ROUTES:
        return LayoutOnlyReviewStrategy(route)
    return LayoutOnlyReviewStrategy(ExtractionRoute.UNKNOWN)
