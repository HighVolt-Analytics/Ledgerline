
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Vendor master detection — four-signal weighted scoring."""

import json
from pathlib import Path

from app.schemas.rule_book_config import (
    BankDetails,
    BillingAddress,
    PostToAccounts,
    PurchaseMatchOn,
    PurchaseRule,
    validate_rule_book_config_payload,
    VendorDetectionWeights,
    VendorMaster,
)
from app.services.invoice_evaluation_service import EVAL_PENDING_VENDOR, evaluate_invoice_routing
from app.services.rule_engine import EvalDocument, detect_vendor
from app.services.vendor_detection import (
    bank_signal_matches,
    find_matching_vendor_master,
    levenshtein_ratio,
    name_signal_matches,
    score_vendor_match,
)
from app.models.invoice import Invoice, InvoiceStatus


def _sysco_master() -> VendorMaster:
    return VendorMaster(
        id="vm-2",
        name="Sysco Australia",
        aliases=["Sysco", "SYSCO AU"],
        abn="11223344556",
        billing_address=BillingAddress(
            street="100 Salmon Street",
            suburb="Port Melbourne VIC",
            postcode="3207",
            country="Australia",
        ),
        bank=BankDetails(
            bsb="033-099",
            account_number="98765432",
            account_name="Sysco Australia Pty Ltd",
            bank_name="Westpac",
        ),
        default_ledger="Raw Materials",
        default_sub_ledger="F&B",
        payment_terms="Net 14",
        status="Active",
        registered_on="2023-11-03",
    )


def test_levenshtein_ratio_close_names() -> None:
    assert levenshtein_ratio("sysco australia", "sysco australi") >= 0.82
    assert levenshtein_ratio("abc", "xyz") < 0.5


def test_name_signal_uses_fuzzy_not_substring_only() -> None:
    master = _sysco_master()
    assert name_signal_matches("Sysco Australa", master)
    assert not name_signal_matches("XYZ Corp", master)


def test_bank_signal_requires_bsb_and_account() -> None:
    master = _sysco_master()
    assert bank_signal_matches("033-099", "98765432", master)
    assert not bank_signal_matches(None, "98765432", master)
    assert not bank_signal_matches("033-099", "11111111", master)


def test_score_vendor_match_all_signals() -> None:
    master = _sysco_master()
    weights = VendorDetectionWeights(name=30, abn=40, bank=20, address=10)
    score = score_vendor_match(
        vendor_name="Sysco Australia",
        abn="11 223 344 556",
        billing_address="100 Salmon Street Port Melbourne VIC 3207",
        bank_bsb="033-099",
        bank_account="98765432",
        master=master,
        weights=weights,
    )
    assert score == 100.0

    assert score_vendor_match(
        vendor_name="Sysco Australia",
        abn="11 223 344 556",
        billing_address=None,
        bank_bsb=None,
        bank_account=None,
        master=master,
        weights=weights,
    ) == 70.0


def test_detect_vendor_identified_at_threshold() -> None:
    config = validate_rule_book_config_payload(
        json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json").read_text(
                encoding="utf-8"
            )
        )
    )
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Sysco Australia Pty Ltd",
        abn="11223344556",
        address="100 Salmon Street Port Melbourne VIC 3207",
        bank_bsb="033-099",
        bank_account="98765432",
    )
    match = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
    assert match.confidence >= 70
    assert match.vendor is not None
    assert match.vendor.name == "Sysco Australia"


def test_detect_vendor_below_threshold_not_identified() -> None:
    config = validate_rule_book_config_payload(
        json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json").read_text(
                encoding="utf-8"
            )
        )
    )
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Sysco Australa",
        abn=None,
        address=None,
    )
    match = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
    assert match.confidence < 70
    assert match.vendor is None


def test_partial_name_match_triggers_pending_vendor() -> None:
    config = validate_rule_book_config_payload(
        json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json").read_text(
                encoding="utf-8"
            )
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Totally Unknown Vendor Pty Ltd",
        invoice_no="PARTIAL-1",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
    )
    result = evaluate_invoice_routing(inv, config, mapping_rule_type="Purchase rule")
    assert result.vendor_confidence < 70
    assert result.evaluation_status in {EVAL_PENDING_VENDOR, "needs_review"}
    assert not any(rule.startswith("vendor:") for rule in result.matched_rule_ids)


def test_known_master_name_match_does_not_trigger_pending_vendor() -> None:
    config = validate_rule_book_config_payload(
        {
            "vendor_masters": [
                {
                    "id": "vm-sysco",
                    "name": "Sysco Foods Australia Pty Ltd",
                    "abn": "51824753556",
                    "default_ledger": "Marketing Expense",
                    "status": "Active",
                }
            ],
            "vendor_detection_config": {
                "threshold": 80,
                "weights": {"name": 30, "abn": 40, "bank": 20, "address": 10},
            },
            "purchase_rules": [
                {
                    "id": "pr-1",
                    "name": "Marketing test POs",
                    "enabled": True,
                    "match_on": {"po_reference_regex": "PO-MKT"},
                    "post_to": {
                        "ledger": "Marketing Expense",
                        "sub_ledger": "",
                        "tax_account": "GST Paid",
                        "payable_account": "Accounts Payable",
                    },
                }
            ],
        }
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Foods Australia Pty Ltd",
        po_reference="PO-MKT-2026-TEST",
        invoice_no="GRN-1",
        status=InvoiceStatus.MAPPING,
    )
    result = evaluate_invoice_routing(inv, config, mapping_rule_type="Purchase rule")
    assert result.vendor_confidence == 30
    assert result.evaluation_status != EVAL_PENDING_VENDOR
    assert any(rule.startswith("vendor:") for rule in result.matched_rule_ids)


def test_find_matching_vendor_master_by_name() -> None:
    master = VendorMaster(
        id="vm-sysco",
        name="Sysco Foods Australia Pty Ltd",
        abn="51824753556",
    )
    hit = find_matching_vendor_master("Sysco Foods Australia Pty Ltd", None, [master])
    assert hit is not None
    assert hit.id == master.id
