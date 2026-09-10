"""Statement parse profiles — locale/format config for bank statement extraction.

``generic_v1`` mirrors the pre-Phase-2 hardcoded defaults exactly. Custom profiles
are resolved by explicit account assignment only (no letterhead auto-ID yet).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

DateOrderSetting = Literal["dmy", "mdy", "ymd", "auto"]
OcrTriggerMode = Literal["chars_only", "chars_or_low_date_density"]
RefineDirectionMode = Literal["only_if_empty", "always", "never"]
MoneyColumnRole = Literal["debit", "credit", "balance", "amount"]

_HEADER_FIELDS = (
    "date",
    "description",
    "debit",
    "credit",
    "amount",
    "direction",
    "balance",
    "reference",
)

# Default phrases for no-amount opening/closing / B/F / C/F marker rows.
_GENERIC_BALANCE_MARKER_PHRASES: tuple[str, ...] = (
    "opening balance",
    "closing balance",
    "balance brought forward",
    "balance carried forward",
    "balance b/f",
    "balance c/f",
    "opening bal",
    "closing bal",
)

# Exact copy of pre-Phase-2 pdf_parser._HEADER_ALIASES.
_GENERIC_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "txn date",
        "transaction date",
        "value date",
        "posting date",
        "tran date",
        "trans date",
        "booking date",
        "process date",
        "processed date",
    ),
    "description": (
        "description",
        "narration",
        "particulars",
        "details",
        "memo",
        "transaction details",
        "transaction description",
        "remarks",
        "narrative",
        "payee",
        "merchant",
        "transaction",
    ),
    "debit": (
        "debit",
        "withdrawal",
        "withdrawals",
        "dr",
        "money out",
        "paid out",
        "outflow",
        "outflows",
        "payments",
        "payment",
        "debit amount",
        "withdrawals (dr)",
        "amount debited",
        "spent",
        "charge",
        "charges",
    ),
    "credit": (
        "credit",
        "deposit",
        "deposits",
        "cr",
        "money in",
        "paid in",
        "inflow",
        "inflows",
        "receipts",
        "receipt",
        "credit amount",
        "deposits (cr)",
        "amount credited",
        "received",
    ),
    "amount": (
        "amount",
        "amt",
        "transaction amount",
        "txn amount",
        "tran amount",
        "value",
        "sum",
    ),
    "direction": (
        "direction",
        "type",
        "dr/cr",
        "dr cr",
        "debit/credit",
        "cd",
        "c/d",
        "txn type",
        "transaction type",
        "flow",
    ),
    "balance": (
        "balance",
        "closing balance",
        "running balance",
        "available balance",
        "ledger balance",
        "book balance",
        "bal",
        "balance (aud)",
        "balance (usd)",
        "balance (inr)",
    ),
    "reference": (
        "reference",
        "ref",
        "ref no",
        "ref.",
        "cheque",
        "chq",
        "chq/ref",
        "cheque no",
        "transaction id",
        "txn id",
        "tran id",
        "fitid",
    ),
}


@dataclass(frozen=True)
class StatementParseProfile:
    profile_id: str
    locale: str = "en"
    date_order: DateOrderSetting = "auto"
    decimal_separator: str = "."
    thousands_separator: str = ","
    encoding_fallbacks: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1252")
    ocr_min_chars: int = 120
    ocr_trigger_mode: OcrTriggerMode = "chars_only"
    refine_direction_mode: RefineDirectionMode = "only_if_empty"
    table_text_coverage_gap_ratio: float = 0.20
    header_aliases: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(_GENERIC_HEADER_ALIASES)
    )
    csv_header_aliases: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(_GENERIC_HEADER_ALIASES)
    )
    money_column_order_hint: tuple[MoneyColumnRole, ...] | None = None
    allow_trailing_minus: bool = False
    balance_marker_phrases: tuple[str, ...] = field(
        default_factory=lambda: tuple(_GENERIC_BALANCE_MARKER_PHRASES)
    )

    @property
    def uses_generic_money(self) -> bool:
        """True when money parsing should match pre-Phase-2 US/AU-style behavior."""
        return (
            self.decimal_separator == "."
            and self.thousands_separator == ","
            and not self.allow_trailing_minus
        )


class StatementParseProfileError(ValueError):
    """Malformed or unknown statement parse profile."""


def _as_alias_map(raw: Any, *, field_name: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise StatementParseProfileError(f"{field_name} must be an object/dict")
    out: dict[str, tuple[str, ...]] = {}
    for key in _HEADER_FIELDS:
        if key not in raw:
            raise StatementParseProfileError(f"{field_name} missing required key: {key}")
        values = raw[key]
        if not isinstance(values, (list, tuple)) or not values:
            raise StatementParseProfileError(
                f"{field_name}.{key} must be a non-empty list of strings"
            )
        cleaned: list[str] = []
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise StatementParseProfileError(
                    f"{field_name}.{key} entries must be non-empty strings"
                )
            cleaned.append(item.strip().lower())
        out[key] = tuple(cleaned)
    return out


def validate_profile_dict(data: Mapping[str, Any]) -> StatementParseProfile:
    """Validate a profile mapping; raise StatementParseProfileError on failure."""
    if not isinstance(data, Mapping):
        raise StatementParseProfileError("profile must be an object/dict")

    profile_id = data.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise StatementParseProfileError("profile_id is required and must be a non-empty string")

    locale = data.get("locale", "en")
    if not isinstance(locale, str) or not locale.strip():
        raise StatementParseProfileError("locale must be a non-empty string")

    date_order = data.get("date_order", "auto")
    if date_order not in {"dmy", "mdy", "ymd", "auto"}:
        raise StatementParseProfileError(
            "date_order must be one of: dmy, mdy, ymd, auto"
        )

    decimal_separator = data.get("decimal_separator", ".")
    thousands_separator = data.get("thousands_separator", ",")
    if not isinstance(decimal_separator, str) or len(decimal_separator) != 1:
        raise StatementParseProfileError("decimal_separator must be a single character")
    if not isinstance(thousands_separator, str) or len(thousands_separator) != 1:
        raise StatementParseProfileError("thousands_separator must be a single character")
    if decimal_separator == thousands_separator:
        raise StatementParseProfileError(
            "decimal_separator and thousands_separator must differ"
        )

    encoding_fallbacks = data.get(
        "encoding_fallbacks", ["utf-8", "utf-8-sig", "cp1252"]
    )
    if (
        not isinstance(encoding_fallbacks, (list, tuple))
        or not encoding_fallbacks
        or not all(isinstance(x, str) and x.strip() for x in encoding_fallbacks)
    ):
        raise StatementParseProfileError(
            "encoding_fallbacks must be a non-empty list of encoding names"
        )

    ocr_min_chars = data.get("ocr_min_chars", 120)
    if not isinstance(ocr_min_chars, int) or ocr_min_chars < 0:
        raise StatementParseProfileError("ocr_min_chars must be a non-negative integer")

    ocr_trigger_mode = data.get("ocr_trigger_mode", "chars_only")
    if ocr_trigger_mode not in {"chars_only", "chars_or_low_date_density"}:
        raise StatementParseProfileError(
            "ocr_trigger_mode must be chars_only or chars_or_low_date_density"
        )

    refine_direction_mode = data.get("refine_direction_mode", "only_if_empty")
    if refine_direction_mode not in {"only_if_empty", "always", "never"}:
        raise StatementParseProfileError(
            "refine_direction_mode must be only_if_empty, always, or never "
            "(always restores pre-Phase-0 overwrite — rarely appropriate)"
        )

    gap = data.get("table_text_coverage_gap_ratio", 0.20)
    if not isinstance(gap, (int, float)) or gap < 0:
        raise StatementParseProfileError(
            "table_text_coverage_gap_ratio must be a non-negative number"
        )

    header_aliases = _as_alias_map(
        data.get("header_aliases", _GENERIC_HEADER_ALIASES),
        field_name="header_aliases",
    )
    csv_header_aliases = _as_alias_map(
        data.get("csv_header_aliases", header_aliases),
        field_name="csv_header_aliases",
    )

    hint = data.get("money_column_order_hint", None)
    money_hint: tuple[MoneyColumnRole, ...] | None
    if hint is None:
        money_hint = None
    else:
        if not isinstance(hint, (list, tuple)) or len(hint) < 2:
            raise StatementParseProfileError(
                "money_column_order_hint must be null or a list of column roles"
            )
        allowed = {"debit", "credit", "balance", "amount"}
        cleaned_hint: list[MoneyColumnRole] = []
        for role in hint:
            if role not in allowed:
                raise StatementParseProfileError(
                    f"money_column_order_hint contains invalid role: {role!r}"
                )
            cleaned_hint.append(role)  # type: ignore[arg-type]
        money_hint = tuple(cleaned_hint)

    allow_trailing_minus = data.get("allow_trailing_minus", False)
    if not isinstance(allow_trailing_minus, bool):
        raise StatementParseProfileError("allow_trailing_minus must be a boolean")

    raw_markers = data.get(
        "balance_marker_phrases", list(_GENERIC_BALANCE_MARKER_PHRASES)
    )
    if (
        not isinstance(raw_markers, (list, tuple))
        or not raw_markers
        or not all(isinstance(x, str) and x.strip() for x in raw_markers)
    ):
        raise StatementParseProfileError(
            "balance_marker_phrases must be a non-empty list of strings"
        )
    balance_marker_phrases = tuple(str(x).strip().lower() for x in raw_markers)

    return StatementParseProfile(
        profile_id=profile_id.strip(),
        locale=locale.strip(),
        date_order=date_order,  # type: ignore[arg-type]
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        encoding_fallbacks=tuple(str(x).strip() for x in encoding_fallbacks),
        ocr_min_chars=ocr_min_chars,
        ocr_trigger_mode=ocr_trigger_mode,  # type: ignore[arg-type]
        refine_direction_mode=refine_direction_mode,  # type: ignore[arg-type]
        table_text_coverage_gap_ratio=float(gap),
        header_aliases=header_aliases,
        csv_header_aliases=csv_header_aliases,
        money_column_order_hint=money_hint,
        allow_trailing_minus=allow_trailing_minus,
        balance_marker_phrases=balance_marker_phrases,
    )


GENERIC_V1 = validate_profile_dict(
    {
        "profile_id": "generic_v1",
        "locale": "en",
        "date_order": "auto",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "encoding_fallbacks": ["utf-8", "utf-8-sig", "cp1252"],
        "ocr_min_chars": 120,
        "ocr_trigger_mode": "chars_only",
        "refine_direction_mode": "only_if_empty",
        "table_text_coverage_gap_ratio": 0.20,
        "header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "csv_header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "money_column_order_hint": None,
        "allow_trailing_minus": False,
        "balance_marker_phrases": list(_GENERIC_BALANCE_MARKER_PHRASES),
    }
)

# EU-style amounts: 1.234,56
EU_DECIMAL_V1 = validate_profile_dict(
    {
        "profile_id": "eu_decimal_v1",
        "locale": "de",
        "date_order": "dmy",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "encoding_fallbacks": ["utf-8", "utf-8-sig", "cp1252"],
        "ocr_min_chars": 120,
        "ocr_trigger_mode": "chars_only",
        "refine_direction_mode": "only_if_empty",
        "table_text_coverage_gap_ratio": 0.20,
        "header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "csv_header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "money_column_order_hint": None,
        "allow_trailing_minus": True,
        "balance_marker_phrases": list(_GENERIC_BALANCE_MARKER_PHRASES),
    }
)

# Fixed MDY for US-style ambiguous numeric dates.
US_MDY_V1 = validate_profile_dict(
    {
        "profile_id": "us_mdy_v1",
        "locale": "en-US",
        "date_order": "mdy",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "encoding_fallbacks": ["utf-8", "utf-8-sig", "cp1252"],
        "ocr_min_chars": 120,
        "ocr_trigger_mode": "chars_only",
        "refine_direction_mode": "only_if_empty",
        "table_text_coverage_gap_ratio": 0.20,
        "header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "csv_header_aliases": {k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
        "money_column_order_hint": None,
        "allow_trailing_minus": False,
        "balance_marker_phrases": list(_GENERIC_BALANCE_MARKER_PHRASES),
    }
)

# Bank vocabulary: Value Dt / Narration / Withdrawal Amt / Deposit Amt
INDIAN_NARRATION_V1 = validate_profile_dict(
    {
        "profile_id": "indian_narration_v1",
        "locale": "en-IN",
        "date_order": "dmy",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "encoding_fallbacks": ["utf-8", "utf-8-sig", "cp1252"],
        "ocr_min_chars": 120,
        "ocr_trigger_mode": "chars_only",
        "refine_direction_mode": "only_if_empty",
        "table_text_coverage_gap_ratio": 0.20,
        "header_aliases": {
            **{k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
            "date": list(_GENERIC_HEADER_ALIASES["date"])
            + ["value dt", "val dt", "txn dt"],
            "description": list(_GENERIC_HEADER_ALIASES["description"])
            + ["narration details"],
            "debit": list(_GENERIC_HEADER_ALIASES["debit"])
            + ["withdrawal amt", "withdrawal amount", "dr amt"],
            "credit": list(_GENERIC_HEADER_ALIASES["credit"])
            + ["deposit amt", "deposit amount", "cr amt"],
        },
        "csv_header_aliases": {
            **{k: list(v) for k, v in _GENERIC_HEADER_ALIASES.items()},
            "date": list(_GENERIC_HEADER_ALIASES["date"]) + ["value dt", "val dt"],
            "debit": list(_GENERIC_HEADER_ALIASES["debit"]) + ["withdrawal amt"],
            "credit": list(_GENERIC_HEADER_ALIASES["credit"]) + ["deposit amt"],
        },
        "money_column_order_hint": None,
        "allow_trailing_minus": False,
        "balance_marker_phrases": list(_GENERIC_BALANCE_MARKER_PHRASES),
    }
)

_PROFILE_REGISTRY: dict[str, StatementParseProfile] = {
    GENERIC_V1.profile_id: GENERIC_V1,
    EU_DECIMAL_V1.profile_id: EU_DECIMAL_V1,
    US_MDY_V1.profile_id: US_MDY_V1,
    INDIAN_NARRATION_V1.profile_id: INDIAN_NARRATION_V1,
}


def register_profile(profile: StatementParseProfile) -> None:
    """Register or replace a profile (tests / future tenant packs)."""
    _PROFILE_REGISTRY[profile.profile_id] = profile


def load_statement_parse_profile(profile_id: str | None) -> StatementParseProfile:
    """Resolve profile by id; None/blank → generic_v1.

    Unknown ids raise — do not silently fall back (malformed assignment).
    """
    if profile_id is None or not str(profile_id).strip():
        return GENERIC_V1
    key = str(profile_id).strip()
    if key not in _PROFILE_REGISTRY:
        raise StatementParseProfileError(
            f"Unknown statement parse profile_id: {key!r}. "
            f"Known: {', '.join(sorted(_PROFILE_REGISTRY))}"
        )
    return _PROFILE_REGISTRY[key]


def profile_from_account(account: Any | None) -> StatementParseProfile:
    """Load profile from a BankAccount (or None → generic_v1)."""
    if account is None:
        return GENERIC_V1
    profile_id = getattr(account, "statement_parse_profile_id", None)
    return load_statement_parse_profile(profile_id)


def list_registered_profile_ids() -> list[str]:
    return sorted(_PROFILE_REGISTRY)


def generic_header_aliases() -> dict[str, tuple[str, ...]]:
    return deepcopy(dict(_GENERIC_HEADER_ALIASES))


def generic_balance_marker_phrases() -> tuple[str, ...]:
    return tuple(_GENERIC_BALANCE_MARKER_PHRASES)
