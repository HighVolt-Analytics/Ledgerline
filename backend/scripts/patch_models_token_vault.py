"""Patch locked model and token_vault files."""

from pathlib import Path

root = Path(__file__).resolve().parents[1] / "app"

# external_accounting_ref
ref_path = root / "models" / "external_accounting_ref.py"
ref_text = ref_path.read_text(encoding="utf-8")
if "sync_status" not in ref_text:
    ref_text = ref_text.replace(
        """    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(512))
    metadata_json: Mapped[str | None] = mapped_column(Text)""",
        """    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(512))
    sync_status: Mapped[str | None] = mapped_column(String(32), index=True)
    sync_attempts: Mapped[int] = mapped_column(default=0)
    sync_error_code: Mapped[str | None] = mapped_column(String(64))
    sync_error_message: Mapped[str | None] = mapped_column(String(512))
    metadata_json: Mapped[str | None] = mapped_column(Text)""",
    )
    ref_path.write_text(ref_text, encoding="utf-8")
    print("external_accounting_ref.py patched")

# token_vault
vault_path = root / "services" / "shared" / "token_vault.py"
vault_path.write_text(
    '''"""Encrypt OAuth tokens at rest using configured encryption material."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _encryption_material() -> bytes:
    source = get_settings().xero_token_encryption_material
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
''',
    encoding="utf-8",
)
print("token_vault.py patched")
