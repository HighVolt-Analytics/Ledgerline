"""Per-country jurisdiction packs — locale/tax/banking DNA (loaded from JSON)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.services.rule_book.tax_invoice_policy import TaxInvoicePolicy

if TYPE_CHECKING:
    from app.models.tenant import Tenant


@dataclass(frozen=True)
class PostingNameDefaults:
    tax_account: str
    payable_account: str
    fallback_account: str
    sales_tax_account: str
    bank_account: str = "Bank Account"
    receivable_account: str = "Accounts Receivable"


@dataclass(frozen=True)
class JurisdictionPack:
    country: str
    currency: str
    timezone: str
    locale: str
    tax_label: str
    statutory_tax_rate: Decimal | None
    tax_id_kind: str
    tax_id_label: str
    bank_routing_label: str
    # Batch bank-payment file format codes this country's banks accept
    # (registry keys in app/services/payments/bank_file_formats), e.g.
    # ("AU_ABA",). Empty until a format for that country is implemented --
    # this only says what COULD be offered, a tenant still opts in via
    # their own BankFileSettings.format.
    bank_file_formats: tuple[str, ...]
    field_labels: dict[str, str]
    llm_tax_id_examples: str
    tax_invoice: TaxInvoicePolicy | None
    posting_defaults: PostingNameDefaults
    match_cap_amount: Decimal


def field_labels_for(*, tax_id: str, tax: str, bank_routing: str) -> dict[str, str]:
    return {
        "abn": tax_id,
        "seller_abn": f"Seller {tax_id}",
        "buyer_abn": f"Buyer {tax_id}",
        "seller_tax_id": f"Seller {tax_id}",
        "buyer_tax_id": f"Buyer {tax_id}",
        "gst": tax,
        "gst_rate": f"{tax} rate",
        "bank_bsb": bank_routing,
        "bank_account": "Account number",
        "bank_name": "Bank name",
        "bank_details": "Bank details",
    }


def jurisdiction_pack_for_country(country_code: str | None) -> JurisdictionPack:
    from app.jurisdiction.loader import get_pack_registry

    registry = get_pack_registry()
    code = (country_code or "").strip().upper()
    if not code:
        return registry.packs[registry.default_country]
    return registry.packs.get(code, registry.generic)


def tenant_jurisdiction(tenant: Tenant | None) -> JurisdictionPack:
    from app.tenant_settings import tenant_country

    return jurisdiction_pack_for_country(tenant_country(tenant))


def jurisdiction_api_view(pack: JurisdictionPack) -> dict[str, object]:
    """Serialize pack fields for institution / settings APIs."""
    rate = pack.statutory_tax_rate
    return {
        "tax_label": pack.tax_label,
        "statutory_tax_rate": float(rate) if rate is not None else None,
        "tax_id_kind": pack.tax_id_kind,
        "tax_id_label": pack.tax_id_label,
        "bank_routing_label": pack.bank_routing_label,
        "field_labels": dict(pack.field_labels),
    }


def __getattr__(name: str):
    """Lazy exports for callers that still import JURISDICTION_PACKS / GENERIC_PACK."""
    if name == "JURISDICTION_PACKS":
        from app.jurisdiction.loader import get_pack_registry

        return get_pack_registry().packs
    if name == "GENERIC_PACK":
        from app.jurisdiction.loader import get_pack_registry

        return get_pack_registry().generic
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
