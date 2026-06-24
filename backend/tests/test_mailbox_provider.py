"""Mailbox provider detection tests."""

from app.services.mailbox_provider import (
    PROVIDER_GOOGLE,
    PROVIDER_MICROSOFT,
    PROVIDER_UNKNOWN,
    available_providers_for_email,
    detect_mailbox_provider,
    resolve_invite_provider,
)


def test_detect_gmail_consumer() -> None:
    assert detect_mailbox_provider("user@gmail.com") == PROVIDER_GOOGLE


def test_detect_iitism_google_workspace() -> None:
    assert detect_mailbox_provider("23je0577@iitism.ac.in") == PROVIDER_GOOGLE


def test_detect_outlook_consumer() -> None:
    assert detect_mailbox_provider("user@outlook.com") == PROVIDER_MICROSOFT


def test_detect_unknown_offers_both_providers() -> None:
    assert detect_mailbox_provider("support@highvolt.tech") == PROVIDER_UNKNOWN
    assert available_providers_for_email("support@highvolt.tech") == [
        PROVIDER_GOOGLE,
        PROVIDER_MICROSOFT,
    ]


def test_resolve_invite_provider_prefers_explicit_choice() -> None:
    assert (
        resolve_invite_provider(
            "support@highvolt.tech",
            stored=PROVIDER_MICROSOFT,
            requested=PROVIDER_GOOGLE,
        )
        == PROVIDER_GOOGLE
    )
