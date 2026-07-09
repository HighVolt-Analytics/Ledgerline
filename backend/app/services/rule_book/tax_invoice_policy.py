"""Per-country tax-invoice wording policies for VR10 (backed by jurisdiction packs)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TaxInvoicePolicy:
    enabled: bool
    phrase_patterns: tuple[re.Pattern[str], ...]
    amount_threshold: Decimal | None
    enforce_when_tax_present: bool


def _patterns(*expressions: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expr, re.I) for expr in expressions)


# Shared phrase sets used when building jurisdiction packs.
TAX_INVOICE_PHRASES = _patterns(r"tax\s+invoice")
VAT_INVOICE_PHRASES = _patterns(r"vat\s+invoice", r"tax\s+invoice")
DE_INVOICE_PHRASES = _patterns(r"rechnung", r"\bust\b", r"mwst", r"tax\s+invoice")

# Back-compat aliases for older imports.
_TAX_INVOICE = TAX_INVOICE_PHRASES
_VAT_INVOICE = VAT_INVOICE_PHRASES
_DE_INVOICE = DE_INVOICE_PHRASES


def tax_invoice_policy_for_country(country_code: str) -> TaxInvoicePolicy | None:
    # Lazy import avoids cycle: packs -> TaxInvoicePolicy/phrases -> this helper.
    from app.jurisdiction.packs import jurisdiction_pack_for_country

    pack = jurisdiction_pack_for_country(country_code)
    return pack.tax_invoice


def document_has_tax_invoice_wording(text: str, policy: TaxInvoicePolicy) -> bool:
    if not text.strip() or not policy.phrase_patterns:
        return False
    return any(pattern.search(text) for pattern in policy.phrase_patterns)
