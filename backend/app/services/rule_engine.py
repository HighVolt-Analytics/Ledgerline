"""Rule book evaluation engine (mirrors frontend rule evaluation logic)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.rule_book_config import (
    EmailCaptureRule,
    ExpenseRule,
    PurchaseRule,
    RuleBookConfigPayload,
    TeamExpenseRule,
    VendorDetectionConfig,
    VendorMaster,
)
from app.services.capture_channel import channel_rule_matches, infer_capture_channel


@dataclass(frozen=True)
class EvalDocument:
    id: str
    doc_number: str
    invoice_no: str
    vendor: str
    abn: str | None = None
    address: str | None = None
    po: str | None = None
    primary_account: str = "Suspense Account"
    lines: tuple[str, ...] = ()
    email_from: str | None = None
    capture_channel: str = "unknown"


@dataclass(frozen=True)
class SampleEmail:
    id: str
    from_addr: str
    to: str
    subject: str
    body: str
    attachment_name: str
    attachment_mime: str


@dataclass(frozen=True)
class VendorMatch:
    vendor: VendorMaster | None
    confidence: float


@dataclass(frozen=True)
class CategoryRuleHit:
    label: str
    kind: Literal["Purchase", "Expense"]


@dataclass(frozen=True)
class LiveEvalRow:
    doc: EvalDocument
    email_rule: EmailCaptureRule | None
    email_rule_disabled: EmailCaptureRule | None
    vendor: VendorMatch
    category_rule: CategoryRuleHit | None
    matched: bool


def _match_value(
    haystack: str,
    operator: str,
    needle: str,
    *,
    case_sensitive: bool | None = None,
) -> bool:
    if case_sensitive:
        a, b = haystack, needle
    else:
        a, b = haystack.lower(), needle.lower()
    if operator == "equals":
        return a == b
    if operator == "not_equals":
        return a != b
    if operator == "contains":
        return b in a
    if operator == "not_contains":
        return b not in a
    if operator == "starts_with":
        return a.startswith(b)
    if operator == "ends_with":
        return a.endswith(b)
    if operator == "regex":
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.search(needle, haystack, flags) is not None
        except re.error:
            return False
    return False


def _email_field(email: SampleEmail, field: str) -> str:
    mapping = {
        "from": email.from_addr,
        "to": email.to,
        "subject": email.subject,
        "body": email.body,
        "attachment_name": email.attachment_name,
        "attachment_mime": email.attachment_mime,
    }
    return mapping.get(field, "")


def _eval_condition(email: SampleEmail, cond: dict[str, Any]) -> bool:
    value = _email_field(email, str(cond.get("field", "")))
    return _match_value(
        value,
        str(cond.get("operator", "")),
        str(cond.get("value", "")),
        case_sensitive=cond.get("case_sensitive"),
    )


def eval_condition_group(email: SampleEmail, group: dict[str, Any]) -> bool:
    children = group.get("children") or []
    if not children:
        return False
    results: list[bool] = []
    for child in children:
        if child.get("type") == "group":
            results.append(eval_condition_group(email, child))
        else:
            results.append(_eval_condition(email, child))
    operator = group.get("operator", "AND")
    return all(results) if operator == "AND" else any(results)


def _mailbox_matches(rule_mailbox: str, mailbox: str | None) -> bool:
    if not mailbox or not rule_mailbox.strip():
        return True
    return rule_mailbox.strip().lower() == mailbox.strip().lower()


def _iter_email_capture_rules(
    rules: list[EmailCaptureRule],
    *,
    enabled_only: bool,
) -> list[EmailCaptureRule]:
    filtered = (rule for rule in rules if rule.enabled == enabled_only)
    return sorted(filtered, key=lambda rule: rule.priority)


def match_email_capture_rule(
    email: SampleEmail,
    rules: list[EmailCaptureRule],
    *,
    mailbox: str | None = None,
) -> EmailCaptureRule | None:
    for rule in _iter_email_capture_rules(rules, enabled_only=True):
        if not _mailbox_matches(rule.mailbox, mailbox or email.to):
            continue
        root = rule.root.model_dump()
        if eval_condition_group(email, root):
            return rule
    return None


def match_disabled_email_capture_rule(
    email: SampleEmail,
    rules: list[EmailCaptureRule],
    *,
    mailbox: str | None = None,
) -> EmailCaptureRule | None:
    """First disabled rule that would match (architecture §2.1 live preview)."""
    for rule in _iter_email_capture_rules(rules, enabled_only=False):
        if not _mailbox_matches(rule.mailbox, mailbox or email.to):
            continue
        root = rule.root.model_dump()
        if eval_condition_group(email, root):
            return rule
    return None


def doc_to_sample_email(doc: EvalDocument, *, default_mailbox: str) -> SampleEmail:
    vendor_slug = doc.vendor.lower().replace(" ", "")
    invoice_ref = doc.invoice_no or doc.doc_number
    attachment = f"{invoice_ref.replace(' ', '')}.pdf"
    from_addr = doc.email_from or f"{vendor_slug}@vendor.example"
    return SampleEmail(
        id=doc.id,
        from_addr=from_addr,
        to=default_mailbox,
        subject=f"{invoice_ref} — {doc.vendor}",
        body=" · ".join(doc.lines),
        attachment_name=attachment,
        attachment_mime="application/pdf",
    )


def match_purchase_rule(doc: EvalDocument, rules: list[PurchaseRule]) -> PurchaseRule | None:
    po_candidates: list[str] = []
    if doc.po:
        po_candidates.append(doc.po)
    if doc.invoice_no:
        po_candidates.append(doc.invoice_no)
    for rule in rules:
        if not rule.enabled:
            continue
        match_on = rule.match_on
        for candidate in po_candidates:
            if match_on.po_prefix and candidate.startswith(match_on.po_prefix):
                return rule
            if match_on.po_regex:
                try:
                    if re.search(match_on.po_regex, candidate):
                        return rule
                except re.error:
                    continue
        if match_on.vendor_contains:
            needle = match_on.vendor_contains.lower()
            if needle in doc.vendor.lower():
                return rule
    return None


def match_expense_rule(doc: EvalDocument, rules: list[ExpenseRule]) -> ExpenseRule | None:
    desc = " ".join(doc.lines).lower()
    doc_number = doc.doc_number.lower()
    for rule in rules:
        if not rule.enabled:
            continue
        match_on = rule.match_on
        if match_on.vendor_contains:
            if match_on.vendor_contains.lower() in doc.vendor.lower():
                return rule
        if match_on.description_contains:
            if match_on.description_contains.lower() in desc:
                return rule
        if match_on.doc_number_contains:
            needle = match_on.doc_number_contains.lower()
            if needle in doc_number or needle in (doc.invoice_no or "").lower():
                return rule
        if match_on.reference_contains:
            ref = (doc.invoice_no or "").lower()
            if match_on.reference_contains.lower() in ref:
                return rule
    return None


def _contains_any_token(haystack: str, pattern: str) -> bool:
    """Match a substring or any slash-separated alternative (e.g. Uber / Ola / Didi)."""
    needle = pattern.strip().lower()
    if not needle:
        return True
    text = haystack.lower()
    if " / " in needle:
        return any(part.strip() in text for part in needle.split(" / ") if part.strip())
    return needle in text


def match_team_expense_rule(
    doc: EvalDocument,
    rules: list[TeamExpenseRule],
    *,
    amount: float | None = None,
) -> TeamExpenseRule | None:
    desc = " ".join(doc.lines).lower()
    merchant = doc.vendor.lower()
    for rule in rules:
        if not rule.enabled:
            continue
        match_on = rule.match_on
        if match_on.description_contains:
            if not _contains_any_token(desc, match_on.description_contains):
                continue
        if match_on.merchant_contains:
            if not _contains_any_token(merchant, match_on.merchant_contains):
                continue
        if match_on.channel_equals:
            channel = doc.capture_channel or infer_capture_channel(doc.email_from)
            if not channel_rule_matches(match_on.channel_equals, channel):
                continue
        if amount is not None:
            if match_on.amount_min is not None and amount < match_on.amount_min:
                continue
            if match_on.amount_max is not None and amount > match_on.amount_max:
                continue
        return rule
    return None


def detect_vendor(
    doc: EvalDocument,
    masters: list[VendorMaster],
    config: VendorDetectionConfig,
    *,
    account_number: str | None = None,
) -> VendorMatch:
    weights = config.weights
    best = VendorMatch(vendor=None, confidence=0.0)
    name = doc.vendor.strip().lower()

    for master in masters:
        score = 0.0
        names = [master.name, *master.aliases]
        names_lower = [entry.lower() for entry in names]
        if name and len(name) >= 4:
            for entry in names_lower:
                if len(entry) >= 4 and (entry in name or name in entry):
                    score += weights.name
                    break
        if doc.abn and doc.abn.strip() and master.abn != "PENDING":
            if doc.abn.replace(" ", "") == master.abn.replace(" ", ""):
                score += weights.abn
        acct = (account_number or "").strip()
        if acct and master.bank.account_number:
            if acct.replace(" ", "") == master.bank.account_number.replace(" ", ""):
                score += weights.bank
        addr = (doc.address or "").strip().lower()
        if addr:
            suburb = master.billing_address.suburb.lower()
            street = master.billing_address.street.lower()
            postcode = master.billing_address.postcode
            if (
                suburb in addr
                or addr in suburb
                or postcode in addr
                or street in addr
                or addr in street
            ):
                score += weights.address
        if score > best.confidence:
            best = VendorMatch(vendor=master, confidence=score)
    return best


def build_live_evaluation(
    docs: list[EvalDocument],
    config: RuleBookConfigPayload,
    *,
    default_mailbox: str = "accounts@acme-hospitality.com.au",
) -> list[LiveEvalRow]:
    rows: list[LiveEvalRow] = []
    for doc in docs:
        email = doc_to_sample_email(doc, default_mailbox=default_mailbox)
        email_rule = match_email_capture_rule(email, config.email_capture_rules)
        email_disabled = None
        if email_rule is None:
            email_disabled = match_disabled_email_capture_rule(
                email,
                config.email_capture_rules,
            )
        vendor = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
        purchase = match_purchase_rule(doc, config.purchase_rules)
        expense = match_expense_rule(doc, config.expense_rules)
        category_rule: CategoryRuleHit | None = None
        if purchase:
            category_rule = CategoryRuleHit(label=purchase.name, kind="Purchase")
        elif expense:
            category_rule = CategoryRuleHit(label=expense.name, kind="Expense")
        matched = vendor.confidence >= config.vendor_detection_config.threshold
        rows.append(
            LiveEvalRow(
                doc=doc,
                email_rule=email_rule,
                email_rule_disabled=email_disabled,
                vendor=vendor,
                category_rule=category_rule,
                matched=matched,
            )
        )
    return rows
