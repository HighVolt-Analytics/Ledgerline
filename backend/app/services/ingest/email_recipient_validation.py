"""Block undeliverable test/fake recipient domains before outbound email."""

from __future__ import annotations

from fastapi import HTTPException

_BLOCKED_EXACT_DOMAINS = frozenset(
    {
        "test.com",
        "example.com",
        "example.org",
        "example.net",
        "fake.com",
        "localhost",
    }
)

_BLOCKED_DOMAIN_SUFFIXES = (
    ".test",
    ".example",
    ".invalid",
    ".localhost",
)


def _domain_from_email(email: str) -> str | None:
    normalized = email.strip().lower()
    if "@" not in normalized:
        return None
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain:
        return None
    return domain


def is_blocked_test_email(email: str) -> bool:
    """Return True when the address uses a known fake or reserved test domain."""
    domain = _domain_from_email(email)
    if domain is None:
        return False
    if domain in _BLOCKED_EXACT_DOMAINS:
        return True
    return any(domain.endswith(suffix) for suffix in _BLOCKED_DOMAIN_SUFFIXES)


def validate_deliverable_email_or_raise(email: str) -> None:
    """Reject test/fake recipient domains before sending outbound email."""
    if is_blocked_test_email(email):
        raise HTTPException(
            status_code=400,
            detail="Please use a real email address. Test domains cannot receive email.",
        )


def mask_email_for_log(email: str) -> str:
    """Mask local part for logs; keep domain visible for deliverability debugging."""
    normalized = email.strip().lower()
    if "@" not in normalized:
        return "***"
    local, domain = normalized.rsplit("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"
