"""Per-country tax-invoice wording policies for VR10."""

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


_TAX_INVOICE = _patterns(r"tax\s+invoice")
_VAT_INVOICE = _patterns(r"vat\s+invoice", r"tax\s+invoice")
_DE_INVOICE = _patterns(r"rechnung", r"\bust\b", r"mwst", r"tax\s+invoice")

COUNTRY_TAX_INVOICE_POLICIES: dict[str, TaxInvoicePolicy] = {
    "AU": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_TAX_INVOICE,
        amount_threshold=Decimal("1000"),
        enforce_when_tax_present=True,
    ),
    "NZ": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_TAX_INVOICE,
        amount_threshold=Decimal("1000"),
        enforce_when_tax_present=True,
    ),
    "SG": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_TAX_INVOICE,
        amount_threshold=None,
        enforce_when_tax_present=True,
    ),
    "GB": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_VAT_INVOICE,
        amount_threshold=None,
        enforce_when_tax_present=True,
    ),
    "DE": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_DE_INVOICE,
        amount_threshold=None,
        enforce_when_tax_present=True,
    ),
    "IN": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_TAX_INVOICE,
        amount_threshold=None,
        enforce_when_tax_present=True,
    ),
    "AE": TaxInvoicePolicy(
        enabled=True,
        phrase_patterns=_VAT_INVOICE,
        amount_threshold=None,
        enforce_when_tax_present=True,
    ),
    "US": TaxInvoicePolicy(
        enabled=False,
        phrase_patterns=(),
        amount_threshold=None,
        enforce_when_tax_present=False,
    ),
}


def tax_invoice_policy_for_country(country_code: str) -> TaxInvoicePolicy | None:
    code = (country_code or "").strip().upper()
    if not code:
        return None
    return COUNTRY_TAX_INVOICE_POLICIES.get(code)


def document_has_tax_invoice_wording(text: str, policy: TaxInvoicePolicy) -> bool:
    if not text.strip() or not policy.phrase_patterns:
        return False
    return any(pattern.search(text) for pattern in policy.phrase_patterns)
