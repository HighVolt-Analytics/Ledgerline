"""Bank narration rule engine — isolated from document eval; RE2 matching."""

from __future__ import annotations

import time
from types import SimpleNamespace

from app.schemas.rule_book_config import (
    BankNarrationMatchOn,
    BankNarrationRule,
    PostToAccounts,
    RuleBookConfigPayload,
)
from app.services.bank_feeds.categorize_service import clear_category_on_match
from app.services.rule_book import rule_engine
from app.services.rule_book.rule_engine import (
    EvalDocument,
    match_bank_narration_rule,
    resolve_category_rule_hit,
)


def _rule(
    *,
    id: str,
    name: str,
    priority: int,
    contains: str | None = None,
    pattern: str | None = None,
    enabled: bool = True,
) -> BankNarrationRule:
    return BankNarrationRule(
        id=id,
        name=name,
        enabled=enabled,
        priority=priority,
        match_on=BankNarrationMatchOn(
            description_contains=contains,
            description_pattern=pattern,
        ),
        post_to=PostToAccounts(ledger="Office Expenses", sub_ledger=""),
    )


def test_empty_match_on_never_matches() -> None:
    rules = [_rule(id="bnr-1", name="Empty", priority=1)]
    assert match_bank_narration_rule("ATM WITHDRAWAL", rules) is None


def test_contains_is_case_insensitive() -> None:
    rules = [_rule(id="bnr-1", name="ATM", priority=10, contains="atm")]
    hit = match_bank_narration_rule("ATM WITHDRAWAL #12", rules)
    assert hit is not None
    assert hit.rule.id == "bnr-1"
    assert hit.matched_on == "contains"
    assert hit.matched_snippet == "atm"


def test_contains_and_pattern_are_anded() -> None:
    rules = [
        _rule(
            id="bnr-and",
            name="Netflix AU",
            priority=10,
            contains="NETFLIX",
            pattern=r"NETFLIX.*AU",
        )
    ]
    assert match_bank_narration_rule("NETFLIX US", rules) is None
    hit = match_bank_narration_rule("NETFLIX AU SUB", rules)
    assert hit is not None
    assert hit.rule.id == "bnr-and"


def test_pattern_is_case_insensitive() -> None:
    rules = [_rule(id="bnr-1", name="Atm", priority=10, pattern=r"atm\s+cash")]
    hit = match_bank_narration_rule("ATM CASH", rules)
    assert hit is not None
    assert hit.rule.id == "bnr-1"


def test_tie_break_lowest_priority_then_list_order() -> None:
    rules = [
        _rule(id="later", name="Later same priority", priority=20, contains="FEE"),
        _rule(id="winner", name="Lower priority", priority=10, contains="FEE"),
        _rule(id="also-10-after", name="Same as winner, later in list", priority=10, contains="FEE"),
    ]
    hit = match_bank_narration_rule("BANK FEE", rules)
    assert hit is not None
    assert hit.rule.id == "winner"


def test_disabled_rules_are_skipped() -> None:
    rules = [
        _rule(id="off", name="Off", priority=1, contains="FEE", enabled=False),
        _rule(id="on", name="On", priority=50, contains="FEE"),
    ]
    hit = match_bank_narration_rule("FEE", rules)
    assert hit is not None
    assert hit.rule.id == "on"


def test_invalid_regex_is_skipped() -> None:
    rules = [
        _rule(id="bad", name="Bad regex", priority=1, pattern="(unclosed"),
        _rule(id="ok", name="Contains", priority=20, contains="ATM"),
    ]
    hit = match_bank_narration_rule("ATM CASH", rules)
    assert hit is not None
    assert hit.rule.id == "ok"


def test_re2_unsupported_backref_is_skipped() -> None:
    rules = [
        _rule(id="bad", name="Backref", priority=1, pattern=r"(fee)\1"),
        _rule(id="ok", name="Contains", priority=20, contains="FEE"),
    ]
    hit = match_bank_narration_rule("FEEFEE", rules)
    assert hit is not None
    assert hit.rule.id == "ok"


def test_catastrophic_pattern_completes_in_linear_time() -> None:
    """RE2 must not hang (or leak a thread) on nested-quantifier patterns."""
    assert not hasattr(rule_engine, "_bank_regex_pool")
    rules = [
        _rule(id="slow", name="Nested", priority=1, pattern=r"(a+)+$"),
        _rule(id="fallback", name="Fallback", priority=20, contains="zzzz"),
    ]
    started = time.monotonic()
    hit = match_bank_narration_rule("a" * 40 + "b", rules)
    elapsed = time.monotonic() - started
    assert hit is None
    assert elapsed < 0.5


def test_catastrophic_pattern_does_not_leak_threads() -> None:
    """Import-time categorize loops must not spawn stuck regex worker threads."""
    import threading

    assert not hasattr(rule_engine, "_bank_regex_pool")
    before = threading.active_count()
    rules = [_rule(id="slow", name="Nested", priority=1, pattern=r"(a+)+$")]
    haystack = "a" * 40 + "b"
    for _ in range(24):
        assert match_bank_narration_rule(haystack, rules) is None
    after = threading.active_count()
    assert after == before


def test_document_eval_never_calls_bank_narration_rules() -> None:
    config = RuleBookConfigPayload(
        bank_narration_rules=[
            _rule(id="bnr-1", name="Streaming", priority=1, contains="NETFLIX"),
        ]
    )
    doc = EvalDocument(
        id="d1",
        doc_number="INV-1",
        invoice_no="INV-1",
        vendor="Netflix",
        lines=("NETFLIX SUBSCRIPTION",),
    )
    hit = resolve_category_rule_hit(doc, config)
    assert hit is None
    bank_hit = match_bank_narration_rule("NETFLIX SUBSCRIPTION", config.bank_narration_rules)
    assert bank_hit is not None
    assert bank_hit.rule.id == "bnr-1"


def test_clear_category_on_match_stashes_history() -> None:
    txn = SimpleNamespace(
        category_coa="Office Expenses",
        review_flags={"categorization": {"source": "rule", "rule_id": "bnr-1"}},
    )
    clear_category_on_match(txn)
    assert txn.category_coa is None
    flags = txn.review_flags
    assert flags["superseded_categorization"]["category_coa"] == "Office Expenses"
    assert "categorization" not in flags
