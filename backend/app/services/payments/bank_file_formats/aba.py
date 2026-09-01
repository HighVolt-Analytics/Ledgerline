"""AU ABA (CEMTEX/APCA) batch payment file writer.

Field positions below match the long-stable, publicly documented CEMTEX/ABA
format Australian banks (CBA, Westpac, ANZ, NAB, and others) use for bulk
payment file uploads -- three fixed-width 120-character record types:
Descriptive (header, "0"), Detail (one per payment, "1"), and File Total
(trailer, "7"). These field widths/positions have been stable for decades.

Two conventions here are the standard, most widely used defaults for a
supplier-payment batch rather than something every bank enforces identically:
transaction code "50" (generic credit/"Pay"), and Total Debit = 0 (this file
only contains credit entries -- the debit side is your own account being
drawn down by your bank when it processes the file, not a detail record in
the file itself). A handful of banks layer extra house rules on top of the
base spec, so verify the first file you generate with your own bank before
relying on it for real payments.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.services.payments.bank_file_formats.base import (
    BankFileFormatError,
    BankFilePaymentLine,
    BankFileRemitter,
    BankFileResult,
)

_RECORD_LEN = 120
_TRANSACTION_CODE_PAY = "50"
_MAX_DETAIL_RECORDS = 999_999  # trailer's "number of records" field is 6 digits


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _text(value: str | None, width: int) -> str:
    """Left justified, space padded, truncated -- standard for name/reference fields."""
    cleaned = (value or "").strip()
    return cleaned[:width].ljust(width)


def _format_bsb(value: str | None, *, field_name: str) -> str:
    digits = _digits_only(value)
    if len(digits) != 6:
        raise BankFileFormatError(
            f"{field_name} must be exactly 6 digits (got {value!r}) -- refusing to "
            "build a payment file with an invalid BSB."
        )
    return f"{digits[:3]}-{digits[3:]}"


def _format_account_number(value: str | None, *, field_name: str) -> str:
    digits = _digits_only(value)
    if not digits:
        raise BankFileFormatError(f"{field_name}: missing account number.")
    if len(digits) > 9:
        raise BankFileFormatError(f"{field_name}: account number {value!r} is longer than 9 digits.")
    return digits.rjust(9)


def _format_amount_cents(amount: Decimal, *, width: int, field_name: str) -> str:
    cents = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
    if cents <= 0:
        raise BankFileFormatError(f"{field_name}: amount must be positive (got {amount}).")
    text = str(cents)
    if len(text) > width:
        raise BankFileFormatError(
            f"{field_name}: amount {amount} needs more than {width} digits of cents -- too large for ABA."
        )
    return text.rjust(width, "0")


class AbaFileFormat:
    """Registry entry for code='AU_ABA'. See module docstring for the spec notes."""

    code = "AU_ABA"
    expected_currency = "AUD"

    def generate(
        self,
        *,
        lines: list[BankFilePaymentLine],
        remitter: BankFileRemitter,
        processing_date: date,
        description: str,
    ) -> BankFileResult:
        if not lines:
            raise BankFileFormatError("No payments to include in the ABA file.")
        if len(lines) > _MAX_DETAIL_RECORDS:
            raise BankFileFormatError(
                f"Too many payments for a single ABA file (max {_MAX_DETAIL_RECORDS})."
            )
        for ln in lines:
            if (ln.currency or "").strip().upper() != self.expected_currency:
                raise BankFileFormatError(
                    f"Payment {ln.payment_id} is in {ln.currency!r}, but AU ABA files must be AUD-only."
                )

        remitter_bsb = _format_bsb(remitter.routing_code, field_name="Your remitting account BSB")
        remitter_acct = _format_account_number(remitter.account_number, field_name="Your remitting account")

        user_id = _digits_only(remitter.extra.get("aba_user_id_number"))
        if not user_id:
            raise BankFileFormatError(
                "Missing APCA User ID Number -- your bank issues this for ABA bulk file "
                "lodgement; set it in Payments → Bank file settings before exporting."
            )
        if len(user_id) > 6:
            raise BankFileFormatError("APCA User ID Number must be at most 6 digits.")
        user_id = user_id.rjust(6, "0")

        institution_code = (remitter.extra.get("aba_financial_institution_code") or "").strip().upper()
        if not institution_code:
            raise BankFileFormatError(
                "Missing your bank's 3-letter APCA code (e.g. CBA, WBC, ANZ, NAB) -- "
                "set it in Payments → Bank file settings before exporting."
            )

        header = (
            "0"
            + " " * 17
            + "01"
            + institution_code.ljust(3)[:3]
            + " " * 7
            + _text(remitter.legal_name, 26)
            + user_id
            + _text(description or "PAYMENTS", 12)
            + processing_date.strftime("%d%m%y")
            + " " * 40
        )
        _assert_record_length(header, "header")

        detail_records: list[str] = []
        total_credit_cents = 0
        for ln in lines:
            bsb = _format_bsb(ln.routing_code, field_name=f"Payment {ln.payment_id} BSB")
            acct = _format_account_number(ln.account_number, field_name=f"Payment {ln.payment_id}")
            amount_cents_str = _format_amount_cents(
                ln.amount, width=10, field_name=f"Payment {ln.payment_id}"
            )
            total_credit_cents += int(amount_cents_str)

            record = (
                "1"
                + bsb
                + acct
                + " "  # indicator (blank for a normal payment)
                + _TRANSACTION_CODE_PAY
                + amount_cents_str
                + _text(ln.account_name or ln.vendor_name, 32)
                + _text(ln.reference, 18)
                + remitter_bsb
                + remitter_acct
                + _text(remitter.display_name, 16)
                + "0" * 8  # withholding tax amount -- not applicable to AP payments
            )
            _assert_record_length(record, f"detail (payment {ln.payment_id})")
            detail_records.append(record)

        total_debit_cents = 0  # credit-only batch -- see module docstring
        net_cents = abs(total_credit_cents - total_debit_cents)
        trailer = (
            "7"
            + "999-999"
            + " " * 12
            + str(net_cents).rjust(10, "0")
            + str(total_credit_cents).rjust(10, "0")
            + str(total_debit_cents).rjust(10, "0")
            + " " * 24
            + str(len(detail_records)).rjust(6, "0")
            + " " * 40
        )
        _assert_record_length(trailer, "trailer")

        content = "\r\n".join([header, *detail_records, trailer]) + "\r\n"
        filename = f"aba_payment_{processing_date.strftime('%Y%m%d')}.aba"
        return BankFileResult(
            filename=filename,
            content=content,
            content_type="text/plain",
            total_amount=Decimal(total_credit_cents) / Decimal(100),
            payment_count=len(detail_records),
        )


def _assert_record_length(record: str, label: str) -> None:
    if len(record) != _RECORD_LEN:
        raise BankFileFormatError(
            f"Internal error: {label} record is {len(record)} chars, expected {_RECORD_LEN}. "
            "Refusing to emit a malformed ABA file."
        )
