"""Jurisdiction pack registry and helpers (JSON-backed)."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.jurisdiction.loader import (
    clear_pack_registry_cache,
    get_pack_registry,
    parse_jurisdiction_catalog,
)
from app.jurisdiction.packs import (
    GENERIC_PACK,
    JURISDICTION_PACKS,
    jurisdiction_api_view,
    jurisdiction_pack_for_country,
)
from app.jurisdiction import tenant_jurisdiction
from app.models.tenant import Tenant
from app.services.extraction.party_field_service import party_llm_rules
from app.services.rule_book.tax_invoice_policy import tax_invoice_policy_for_country
from app.utils.tax_id_validator import is_acceptable_tax_id

_SHIPPED = Path(__file__).resolve().parents[1] / "data" / "jurisdiction_packs.json"


def test_all_supported_packs_coherent() -> None:
    for code, pack in JURISDICTION_PACKS.items():
        assert pack.country == code
        assert pack.currency
        assert pack.tax_label
        assert pack.tax_id_kind
        assert pack.tax_id_label
        assert "abn" in pack.field_labels
        assert "gst" in pack.field_labels
        assert pack.match_cap_amount > 0
        assert pack.posting_defaults.tax_account
        assert pack.posting_defaults.payable_account


def test_default_country_is_sg() -> None:
    pack = jurisdiction_pack_for_country(None)
    assert pack.country == "SG"
    assert pack.currency == "SGD"
    assert pack.statutory_tax_rate == Decimal("9")


def test_unknown_country_is_generic_not_au() -> None:
    pack = jurisdiction_pack_for_country("ZZ")
    assert pack.country == GENERIC_PACK.country
    assert pack.tax_id_kind == "generic"
    assert pack.statutory_tax_rate is None
    assert pack.tax_invoice is None


def test_au_compliance_pack() -> None:
    pack = jurisdiction_pack_for_country("AU")
    assert pack.tax_id_kind == "abn"
    assert pack.statutory_tax_rate == Decimal("10")
    assert pack.tax_invoice is not None
    assert pack.tax_invoice.amount_threshold == Decimal("1000")
    assert pack.posting_defaults.tax_account == "GST Paid"


def test_tax_invoice_policy_delegates_to_pack() -> None:
    au = tax_invoice_policy_for_country("AU")
    us = tax_invoice_policy_for_country("US")
    assert au is not None and au.enabled
    assert us is not None and not us.enabled


def test_tenant_jurisdiction() -> None:
    tenant = Tenant(name="GB Co", slug="gb", settings_json={"country": "GB"})
    pack = tenant_jurisdiction(tenant)
    assert pack.tax_label == "VAT"
    assert pack.currency == "GBP"
    assert pack.bank_routing_label == "Sort code"


def test_api_view_serializes_rate() -> None:
    view = jurisdiction_api_view(jurisdiction_pack_for_country("SG"))
    assert view["tax_label"] == "GST"
    assert view["statutory_tax_rate"] == 9.0
    assert view["tax_id_kind"] == "uen"


def test_party_llm_rules_are_country_aware() -> None:
    au = party_llm_rules(jurisdiction_pack_for_country("AU"))
    sg = party_llm_rules(jurisdiction_pack_for_country("SG"))
    assert "ABN" in au or "45123456789" in au
    assert "UEN" in sg
    assert "45123456789" not in sg


def test_tax_id_kind_dispatch() -> None:
    assert is_acceptable_tax_id("51824753556", tax_id_kind="abn")
    assert not is_acceptable_tax_id("12345678901", tax_id_kind="abn")
    assert is_acceptable_tax_id("201912345A", tax_id_kind="uen")
    assert is_acceptable_tax_id("IE6388047V", tax_id_kind="vat")


def test_shipped_json_parses() -> None:
    import json

    raw = json.loads(_SHIPPED.read_text(encoding="utf-8"))
    registry = parse_jurisdiction_catalog(raw)
    assert registry.default_country == "SG"
    assert "SG" in registry.packs
    assert registry.packs["SG"].statutory_tax_rate == Decimal("9")
    assert registry.generic.tax_id_kind == "generic"


def test_parse_rejects_empty_packs() -> None:
    with pytest.raises(ValueError, match="packs"):
        parse_jurisdiction_catalog({"default_country": "AU", "packs": {}})


def test_phrase_patterns_compile() -> None:
    pack = jurisdiction_pack_for_country("DE")
    assert pack.tax_invoice is not None
    assert pack.tax_invoice.phrase_patterns
    assert any(p.search("Rechnung") for p in pack.tax_invoice.phrase_patterns)


def test_registry_cache_clear(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json

    alt = {
        "default_country": "SG",
        "packs": {
            "SG": {
                "currency": "SGD",
                "timezone": "Asia/Singapore",
                "locale": "en-SG",
                "tax_label": "GST",
                "statutory_tax_rate": 9,
                "tax_id_kind": "uen",
                "tax_id_label": "UEN",
                "bank_routing_label": "Bank code",
                "llm_tax_id_examples": "placeholder",
                "match_cap_amount": 100,
                "posting_defaults": {
                    "tax_account": "GST Paid",
                    "payable_account": "Accounts Payable",
                    "fallback_account": "Suspense Account",
                    "sales_tax_account": "GST Collected",
                },
                "tax_invoice": None,
            }
        },
        "generic": {
            "country": "XX",
            "currency": "SGD",
            "timezone": "Asia/Singapore",
            "locale": "en-SG",
            "tax_label": "Tax",
            "statutory_tax_rate": None,
            "tax_id_kind": "generic",
            "tax_id_label": "Tax ID",
            "bank_routing_label": "Bank code",
            "llm_tax_id_examples": "placeholder",
            "match_cap_amount": 100,
            "posting_defaults": {
                "tax_account": "Tax Paid",
                "payable_account": "Accounts Payable",
                "fallback_account": "Suspense Account",
                "sales_tax_account": "Tax Collected",
            },
            "tax_invoice": None,
        },
    }
    path = tmp_path / "packs.json"
    path.write_text(json.dumps(alt), encoding="utf-8")
    monkeypatch.setenv("JURISDICTION_PACKS_PATH", str(path))
    from app.config import get_settings

    get_settings.cache_clear()
    clear_pack_registry_cache()
    registry = get_pack_registry()
    assert registry.default_country == "SG"
    assert jurisdiction_pack_for_country(None).country == "SG"
    # Restore shipped catalog for later tests in this process.
    monkeypatch.delenv("JURISDICTION_PACKS_PATH", raising=False)
    get_settings.cache_clear()
    clear_pack_registry_cache()
    assert jurisdiction_pack_for_country(None).country == "SG"
