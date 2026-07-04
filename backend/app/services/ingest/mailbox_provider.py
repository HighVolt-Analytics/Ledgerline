"""Detect whether a mailbox is hosted on Google or Microsoft."""

from __future__ import annotations

from typing import Literal

MailProvider = Literal["google", "microsoft", "unknown"]

PROVIDER_GOOGLE = "google"
PROVIDER_MICROSOFT = "microsoft"
PROVIDER_UNKNOWN = "unknown"

_GOOGLE_EMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_MICROSOFT_CONSUMER_DOMAINS = frozenset(
    {"outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com"}
)
# Domains known to use Google Workspace (extend as needed).
_GOOGLE_WORKSPACE_DOMAINS = frozenset({"iitism.ac.in"})


def email_domain(email: str) -> str:
    return email.strip().lower().split("@")[-1]


def detect_mailbox_provider(email: str) -> MailProvider:
    """Best-effort provider guess from the mailbox address."""
    domain = email_domain(email)
    if not domain or "@" in domain:
        return PROVIDER_UNKNOWN
    if domain in _GOOGLE_EMAIL_DOMAINS or domain in _GOOGLE_WORKSPACE_DOMAINS:
        return PROVIDER_GOOGLE
    if domain in _MICROSOFT_CONSUMER_DOMAINS or domain.endswith(".onmicrosoft.com"):
        return PROVIDER_MICROSOFT
    return PROVIDER_UNKNOWN


def resolve_invite_provider(
    requested_email: str,
    *,
    stored: str | None = None,
    requested: str | None = None,
) -> MailProvider:
    """Pick OAuth provider for an invite (explicit choice wins, then stored, then detect)."""
    if requested in (PROVIDER_GOOGLE, PROVIDER_MICROSOFT):
        return requested
    if stored in (PROVIDER_GOOGLE, PROVIDER_MICROSOFT):
        return stored
    return detect_mailbox_provider(requested_email)


def available_providers_for_email(email: str) -> list[MailProvider]:
    detected = detect_mailbox_provider(email)
    if detected == PROVIDER_GOOGLE:
        return [PROVIDER_GOOGLE]
    if detected == PROVIDER_MICROSOFT:
        return [PROVIDER_MICROSOFT]
    return [PROVIDER_GOOGLE, PROVIDER_MICROSOFT]
