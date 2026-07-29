"""Processing override catalog helpers."""

from __future__ import annotations

import pytest

from app.services.invoice.processing_override_catalog import (
    normalise_processing_overrides,
    override_bypasses_purchase_hold,
    override_bypasses_sales_hold,
    serialise_processing_overrides,
    should_skip,
    validate_skip_steps,
)
from app.models.invoice import Invoice
from app.tenant_ids import TESTING_TENANT_UUID


def test_validate_skip_steps_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown processing override"):
        validate_skip_steps(["not_a_real_step"])


def test_normalise_processing_overrides_filters_invalid() -> None:
    payload = normalise_processing_overrides(
        {"skip_steps": ["validation", "bogus", "playbook"]}
    )
    assert payload.skip_steps == ["playbook", "validation"]


def test_should_skip_reads_invoice_column() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        currency="AUD",
        processing_overrides={"skip_steps": ["validation"]},
    )
    assert should_skip(inv, "validation")
    assert not should_skip(inv, "playbook")


def test_override_bypasses_purchase_hold() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        currency="AUD",
        processing_overrides={"skip_steps": ["playbook"]},
    )
    assert override_bypasses_purchase_hold(inv)
    inv.processing_overrides = None
    assert not override_bypasses_purchase_hold(inv)


def test_override_bypasses_sales_hold() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        currency="AUD",
        processing_overrides={"skip_steps": ["playbook"]},
    )
    assert override_bypasses_sales_hold(inv)
    inv.processing_overrides = None
    assert not override_bypasses_sales_hold(inv)


def test_serialise_empty_returns_none() -> None:
    assert serialise_processing_overrides([]) is None
