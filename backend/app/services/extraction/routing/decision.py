"""Route decision produced by the extraction router."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.extraction.routing.routes import ExtractionRoute


@dataclass(frozen=True)
class DocumentRouteDecision:
    route: ExtractionRoute
    confirmed_dt: str = ""
    playbook: str = ""
    reasons: tuple[str, ...] = ()
    classifier_source: str = "dt_map"
    allow_invoice_model: bool = False
    review_hints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def uses_invoice_model(self) -> bool:
        from app.services.extraction.routing.routes import INVOICE_FAMILY_ROUTES

        if self.route in INVOICE_FAMILY_ROUTES:
            return True
        if self.route == ExtractionRoute.EXPENSE_CLAIM and self.allow_invoice_model:
            return True
        return False
