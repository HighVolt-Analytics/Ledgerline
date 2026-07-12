"""Role-prefix / packing-suffix contamination stripping on vendor names."""

from __future__ import annotations

from app.services.master_data.bundle_vendor_service import resolve_canonical_vendor_name
from app.services.master_data.vendor_name_utils import (
    is_plausible_vendor_name,
    normalize_vendor_name,
)
from app.services.sales.counterparty_service import resolve_counterparty_name
from app.services.tenant.tenant_org_context import OrgContext
from tests.rule_book_test_helpers import demo_rule_book_config

ORG = OrgContext(
    legal_name="Highvolt Industries Pty Ltd",
    abn="12345678901",
    default_perspective="buyer",
)


def test_invoice_184_strips_buyer_prefix_and_plot_address() -> None:
    assert (
        normalize_vendor_name("BUYER Bluepeak Industries Pvt Ltd Plot 14,")
        == "Bluepeak Industries Pvt Ltd"
    )


def test_invoice_251_strips_packing_qty_suffix() -> None:
    assert (
        normalize_vendor_name("CLASSIC ENTERPRISE (AN) => 50 cartons")
        == "CLASSIC ENTERPRISE (AN)"
    )


def test_packing_qty_suffix_variants() -> None:
    assert normalize_vendor_name("Acme Trading - 10 units") == "Acme Trading"
    assert normalize_vendor_name("Acme Trading x 20 pcs") == "Acme Trading"
    assert normalize_vendor_name("Acme Trading => 3 pallets") == "Acme Trading"


def test_pure_role_markers_still_rejected() -> None:
    assert normalize_vendor_name("CONSIGNEE") is None
    assert normalize_vendor_name("BUYER ") is None
    assert normalize_vendor_name("BUYER") is None
    assert not is_plausible_vendor_name("CONSIGNEE")
    assert not is_plausible_vendor_name("BUYER")


def test_exact_label_rejections_unchanged() -> None:
    assert not is_plausible_vendor_name("Pre-carriage by")
    assert not is_plausible_vendor_name("Port of Loading")
    assert not is_plausible_vendor_name("Invoice Number :")
    assert not is_plausible_vendor_name(
        "Invoice Date: Please reference the invoice number with payment"
    )
    assert normalize_vendor_name("Port of Loading") is None
    assert normalize_vendor_name("Pre-carriage by") is None
    assert is_plausible_vendor_name("Atlassian Pty Ltd")


def test_date_only_strings_rejected_as_vendor() -> None:
    assert normalize_vendor_name("01/07/2026") is None
    assert normalize_vendor_name("15/06/2026") is None
    assert normalize_vendor_name("2026-07-01") is None
    assert normalize_vendor_name("1 July 2026") is None
    assert not is_plausible_vendor_name("01/07/2026")
    assert is_plausible_vendor_name("Sysco Australia Pty Ltd")


def test_consignee_prefix_with_real_name_is_salvaged() -> None:
    assert (
        normalize_vendor_name("Consignee Acme Logistics Pty Ltd")
        == "Acme Logistics Pty Ltd"
    )


def test_counterparty_resolve_strips_contaminated_generic() -> None:
    resolved = resolve_counterparty_name(
        side="vendor",
        org=ORG,
        seller_name="BUYER Bluepeak Industries Pvt Ltd Plot 14,",
        buyer_name="Highvolt Industries Pty Ltd",
        generic_name="CLASSIC ENTERPRISE (AN) => 50 cartons",
    )
    assert resolved == "Bluepeak Industries Pvt Ltd"


def test_canonical_vendor_tier4_strips_contamination() -> None:
    config = demo_rule_book_config()
    assert (
        resolve_canonical_vendor_name(
            1,
            vendor_names=["CLASSIC ENTERPRISE (AN) => 50 cartons"],
            config=config,
        )
        == "CLASSIC ENTERPRISE (AN)"
    )
    assert (
        resolve_canonical_vendor_name(
            1,
            vendor_names=["BUYER Bluepeak Industries Pvt Ltd Plot 14,"],
            config=config,
        )
        == "Bluepeak Industries Pvt Ltd"
    )
