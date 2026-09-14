"""Counterparty-aware VR12/VR13 behaviour."""

from __future__ import annotations

from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.extended_validations import (
    vr12_counterparty_master,
    vr13_bank_details_match,
)


def test_vr12_skips_none_and_employee() -> None:
    data = InvoiceData(vendor="Acme Pty Ltd")
    none_result = vr12_counterparty_master(
        data,
        route_target="Vault",
        counterparty_type="none",
        vendor_masters=[],
        customer_masters=[],
    )
    assert none_result.skipped is True
    assert none_result.passed is True

    employee_result = vr12_counterparty_master(
        data,
        route_target="Team Expenses",
        counterparty_type="employee",
        vendor_masters=[],
        customer_masters=[],
    )
    assert employee_result.skipped is True
    assert employee_result.passed is True


def test_vr13_skips_non_vendor_counterparties() -> None:
    data = InvoiceData(vendor="Acme Pty Ltd", bank_bsb="062-000", bank_account="12345678")
    for token in ("none", "employee", "customer"):
        result = vr13_bank_details_match(data, vendor_masters=[], counterparty_type=token)
        assert result.skipped is True
        assert result.passed is True
