"""Shared types every batch bank-payment file format writer implements against.

Keeping these format-agnostic (no "bsb" field name, no assumption about fixed
width vs XML, etc.) is what lets a second country's format (NACHA, SEPA,
BACS...) plug in later without reshaping the payments/vendor data this
package is handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class BankFilePaymentLine:
    """One outgoing payment, already normalized for any format writer.

    routing_code/account_number are raw as stored (may contain spaces or
    dashes) -- each format writer is responsible for normalizing to its own
    field-width/character rules, since those rules differ per format.
    """

    payment_id: int
    vendor_name: str
    amount: Decimal
    currency: str
    reference: str  # shown on the RECIPIENT's bank statement
    bank_name: str
    routing_code: str
    account_number: str
    account_name: str  # name on the recipient's bank account


@dataclass(frozen=True)
class BankFileRemitter:
    """The tenant's own account originating the file (see RemitterBankAccount)."""

    legal_name: str
    display_name: str  # short name shown on recipients' statements
    bank_name: str
    routing_code: str
    account_number: str
    # Format-specific extras that don't belong on the generic remitter shape,
    # e.g. {"aba_user_id_number": "123456"} for AU ABA.
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BankFileResult:
    filename: str
    content: str
    content_type: str = "text/plain"
    total_amount: Decimal = Decimal("0")
    payment_count: int = 0


class BankFileFormatError(ValueError):
    """Payments/remitter data can't be safely turned into this file format."""


class BankFileFormat(Protocol):
    """One bulk-payment file format (e.g. Australia's ABA/CEMTEX format)."""

    code: str  # registry key, e.g. "AU_ABA"
    expected_currency: str  # a batch mixing currencies is always rejected

    def generate(
        self,
        *,
        lines: list[BankFilePaymentLine],
        remitter: BankFileRemitter,
        processing_date: date,
        description: str,
    ) -> BankFileResult:
        """Build the file. Must raise BankFileFormatError on unsafe/invalid input
        rather than emit a partially-wrong file -- a malformed batch payment file
        can misdirect real money, so failing loudly beats guessing.
        """
        ...
