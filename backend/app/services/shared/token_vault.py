"""Encrypt OAuth tokens at rest using the app JWT secret or optional accounting key."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _encryption_material() -> bytes:
    explicit = (os.getenv("XERO_TOKEN_ENCRYPTION_KEY") or "").strip()
    source = explicit or get_settings().jwt_secret
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_encryption_material())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
