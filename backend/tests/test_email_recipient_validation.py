"""Tests for outbound email recipient domain validation."""

import pytest
from fastapi import HTTPException

from app.services.ingest.email_recipient_validation import (
    is_blocked_test_email,
    validate_deliverable_email_or_raise,
)


@pytest.mark.parametrize(
    "email",
    [
        "accept-me@test.com",
        "user@example.com",
        "user@example.org",
        "user@fake.com",
        "user@domain.invalid",
        "admin@localhost",
        "x@sub.example",
    ],
)
def test_blocked_test_emails(email: str) -> None:
    assert is_blocked_test_email(email) is True
    with pytest.raises(HTTPException) as exc_info:
        validate_deliverable_email_or_raise(email)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Please use a real email address. Test domains cannot receive email."
    )


@pytest.mark.parametrize(
    "email",
    [
        "dhiren@highvolt.tech",
        "user@gmail.com",
        "user@outlook.com",
        "user@hotmail.com",
        "user@microsoft.com",
        "admin@acme.com",
    ],
)
def test_allowed_real_emails(email: str) -> None:
    assert is_blocked_test_email(email) is False
    validate_deliverable_email_or_raise(email)
