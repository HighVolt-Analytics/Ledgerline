"""Load jurisdiction packs from shipped JSON config."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.jurisdiction.packs import JurisdictionPack, PostingNameDefaults, field_labels_for
from app.services.rule_book.tax_invoice_policy import TaxInvoicePolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JurisdictionPackRegistry:
    default_country: str
    packs: dict[str, JurisdictionPack]
    generic: JurisdictionPack


def _catalog_path() -> Path:
    from app.config import get_settings

    return Path(get_settings().jurisdiction_packs_path)


def _compile_phrases(raw: Any) -> tuple[re.Pattern[str], ...]:
    if not isinstance(raw, list):
        return ()
    patterns: list[re.Pattern[str]] = []
    for item in raw:
        expr = str(item or "").strip()
        if not expr:
            continue
        patterns.append(re.compile(expr, re.I))
    return tuple(patterns)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _posting(raw: Any | None) -> PostingNameDefaults:
    data = raw if isinstance(raw, dict) else {}
    return PostingNameDefaults(
        tax_account=str(data.get("tax_account") or "Tax Paid"),
        payable_account=str(data.get("payable_account") or "Accounts Payable"),
        fallback_account=str(data.get("fallback_account") or "Suspense Account"),
        sales_tax_account=str(data.get("sales_tax_account") or "Tax Collected"),
    )


def _tax_invoice(raw: Any | None) -> TaxInvoicePolicy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    threshold = _decimal_or_none(raw.get("amount_threshold"))
    return TaxInvoicePolicy(
        enabled=bool(raw.get("enabled", False)),
        phrase_patterns=_compile_phrases(raw.get("phrase_patterns")),
        amount_threshold=threshold,
        enforce_when_tax_present=bool(raw.get("enforce_when_tax_present", False)),
    )


def _pack_from_dict(country: str, data: dict[str, Any]) -> JurisdictionPack:
    tax_label = str(data.get("tax_label") or "Tax")
    tax_id_label = str(data.get("tax_id_label") or "Tax ID")
    bank_routing_label = str(data.get("bank_routing_label") or "Bank code")
    match_cap = _decimal_or_none(data.get("match_cap_amount")) or Decimal("100")
    code = str(data.get("country") or country).strip().upper() or country
    return JurisdictionPack(
        country=code,
        currency=str(data.get("currency") or "SGD").strip().upper() or "SGD",
        timezone=str(data.get("timezone") or "Asia/Singapore"),
        locale=str(data.get("locale") or "en-SG"),
        tax_label=tax_label,
        statutory_tax_rate=_decimal_or_none(data.get("statutory_tax_rate")),
        tax_id_kind=str(data.get("tax_id_kind") or "generic").strip().lower() or "generic",
        tax_id_label=tax_id_label,
        bank_routing_label=bank_routing_label,
        field_labels=field_labels_for(
            tax_id=tax_id_label,
            tax=tax_label,
            bank_routing=bank_routing_label,
        ),
        llm_tax_id_examples=str(data.get("llm_tax_id_examples") or "placeholder tax IDs"),
        tax_invoice=_tax_invoice(data.get("tax_invoice")),
        posting_defaults=_posting(data.get("posting_defaults")),
        match_cap_amount=match_cap,
    )


def _minimal_generic() -> JurisdictionPack:
    return JurisdictionPack(
        country="XX",
        currency="SGD",
        timezone="Asia/Singapore",
        locale="en-SG",
        tax_label="Tax",
        statutory_tax_rate=None,
        tax_id_kind="generic",
        tax_id_label="Tax ID",
        bank_routing_label="Bank code",
        field_labels=field_labels_for(tax_id="Tax ID", tax="Tax", bank_routing="Bank code"),
        llm_tax_id_examples="placeholder tax IDs",
        tax_invoice=None,
        posting_defaults=_posting(None),
        match_cap_amount=Decimal("100"),
    )


def parse_jurisdiction_catalog(raw: dict[str, Any]) -> JurisdictionPackRegistry:
    default_country = str(raw.get("default_country") or "SG").strip().upper() or "SG"
    packs_raw = raw.get("packs")
    if not isinstance(packs_raw, dict) or not packs_raw:
        raise ValueError("jurisdiction_packs.json missing non-empty 'packs' object")

    packs: dict[str, JurisdictionPack] = {}
    for code, body in packs_raw.items():
        if not isinstance(body, dict):
            continue
        key = str(code).strip().upper()
        if not key:
            continue
        packs[key] = _pack_from_dict(key, body)

    if not packs:
        raise ValueError("jurisdiction_packs.json has no valid pack entries")

    generic_raw = raw.get("generic")
    if isinstance(generic_raw, dict):
        generic = _pack_from_dict("XX", generic_raw)
    else:
        generic = _minimal_generic()

    if default_country not in packs:
        # Prefer first pack over inventing a country; keep declared default if somehow only generic.
        default_country = next(iter(packs))

    return JurisdictionPackRegistry(
        default_country=default_country,
        packs=packs,
        generic=generic,
    )


def _load_registry_from_path(path: Path) -> JurisdictionPackRegistry:
    import json

    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("jurisdiction_packs.json root must be an object")
    return parse_jurisdiction_catalog(raw)


@lru_cache(maxsize=1)
def get_pack_registry() -> JurisdictionPackRegistry:
    path = _catalog_path()
    try:
        return _load_registry_from_path(path)
    except FileNotFoundError:
        logger.exception("Jurisdiction packs file missing at %s — using minimal generic registry", path)
        generic = _minimal_generic()
        return JurisdictionPackRegistry(default_country="SG", packs={"SG": generic}, generic=generic)
    except Exception:
        logger.exception("Failed to load jurisdiction packs from %s — using minimal generic registry", path)
        generic = _minimal_generic()
        return JurisdictionPackRegistry(default_country="SG", packs={"SG": generic}, generic=generic)


def clear_pack_registry_cache() -> None:
    get_pack_registry.cache_clear()


def load_jurisdiction_packs_for_tests(path: Path | str) -> JurisdictionPackRegistry:
    """Load packs from an explicit path (tests); updates the module cache."""
    clear_pack_registry_cache()
    registry = _load_registry_from_path(Path(path))

    @lru_cache(maxsize=1)
    def _cached() -> JurisdictionPackRegistry:
        return registry

    # Replace cache by clearing and monkeypatching is awkward; prefer direct return +
    # tests set JURISDICTION_PACKS_PATH. Keep helper for parse assertions.
    return registry


def country_locale_map() -> dict[str, dict[str, str]]:
    return {
        code: {"timezone": pack.timezone, "locale": pack.locale}
        for code, pack in get_pack_registry().packs.items()
    }


def country_currency_map() -> dict[str, str]:
    return {code: pack.currency for code, pack in get_pack_registry().packs.items()}


def pack_country_codes() -> frozenset[str]:
    return frozenset(get_pack_registry().packs.keys())
