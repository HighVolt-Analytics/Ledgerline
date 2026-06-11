"""Rule book evaluation engine (mirrors frontend rule evaluation logic)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

PurchaseDocumentType = Literal["po", "grn", "invoice"]
PURCHASE_DOCUMENT_TYPES = frozenset({"po", "grn", "invoice"})

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
    email_subject: str | None = None
    email_attachment_name: str | None = None
    capture_channel: str = "unknown"
    document_type: PurchaseDocumentType = "invoice"
    bank_bsb: str | None = None
    bank_account: str | None = None


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
    kind: Literal["Purchase", "Expense", "Team"]


@dataclass(frozen=True)
class LiveEvalRow:
    doc: EvalDocument
    email_rule: EmailCaptureRule | None
    email_rule_disabled: EmailCaptureRule | None
    vendor: VendorMatch
    category_rule: CategoryRuleHit | None
    category_rule_disabled: CategoryRuleHit | None
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
            sub_children = child.get("children") or []
            if not sub_children:
                # Empty groups saved by the UI should not block AND rules.
                continue
            results.append(eval_condition_group(email, child))
        else:
            results.append(_eval_condition(email, child))
    if not results:
        return False
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
    attachment = doc.email_attachment_name or f"{invoice_ref.replace(' ', '')}.pdf"
    from_addr = doc.email_from or f"{vendor_slug}@vendor.example"
    subject = doc.email_subject or f"{invoice_ref} — {doc.vendor}"
    return SampleEmail(
        id=doc.id,
        from_addr=from_addr,
        to=default_mailbox,
        subject=subject,
        body=" · ".join(doc.lines),
        attachment_name=attachment,
        attachment_mime="application/pdf",
    )


def _iter_category_rules(rules: list, *, enabled_only: bool) -> list:
    filtered = (rule for rule in rules if rule.enabled == enabled_only)
    return sorted(filtered, key=lambda rule: rule.priority)


def _po_number_matches_rule(rule: PurchaseRule, po_number: str) -> bool:
    match_on = rule.match_on
    if match_on.po_prefix and po_number.startswith(match_on.po_prefix):
        return True
    if match_on.po_regex:
        try:
            return re.search(match_on.po_regex, po_number) is not None
        except re.error:
            return False
    return False


def _purchase_rule_matches(doc: EvalDocument, rule: PurchaseRule) -> bool:
    """Architecture §4.3 — all conditions must hold for PO / GRN / Invoice."""
    doc_type = doc.document_type or "invoice"
    if doc_type not in PURCHASE_DOCUMENT_TYPES:
        return False

    match_on = rule.match_on
    if not match_on.po_prefix and not match_on.po_regex:
        return False

    po_number = (doc.po or "").strip()
    if not po_number:
        return False
    if not _po_number_matches_rule(rule, po_number):
        return False

    if doc_type == "grn" and not match_on.grn_linked_to_po:
        return False
    if doc_type == "invoice" and not match_on.invoice_references_po:
        return False

    if match_on.vendor_contains:
        needle = match_on.vendor_contains.lower()
        if needle not in (doc.vendor or "").lower():
            return False

    return True


def match_purchase_rule(doc: EvalDocument, rules: list[PurchaseRule]) -> PurchaseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=True):
        if _purchase_rule_matches(doc, rule):
            return rule
    return None


def match_disabled_purchase_rule(
    doc: EvalDocument,
    rules: list[PurchaseRule],
) -> PurchaseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=False):
        if _purchase_rule_matches(doc, rule):
            return rule
    return None


def _expense_rule_matches(doc: EvalDocument, rule: ExpenseRule) -> bool:
    desc = " ".join(doc.lines).lower()
    doc_number = doc.doc_number.lower()
    match_on = rule.match_on
    if match_on.vendor_contains:
        if match_on.vendor_contains.lower() in doc.vendor.lower():
            return True
    if match_on.description_contains:
        if match_on.description_contains.lower() in desc:
            return True
    if match_on.doc_number_contains:
        needle = match_on.doc_number_contains.lower()
        if needle in doc_number or needle in (doc.invoice_no or "").lower():
            return True
    if match_on.reference_contains:
        ref = (doc.invoice_no or "").lower()
        if match_on.reference_contains.lower() in ref:
            return True
    return False


def match_expense_rule(doc: EvalDocument, rules: list[ExpenseRule]) -> ExpenseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=True):
        if _expense_rule_matches(doc, rule):
            return rule
    return None


def match_disabled_expense_rule(
    doc: EvalDocument,
    rules: list[ExpenseRule],
) -> ExpenseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=False):
        if _expense_rule_matches(doc, rule):
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


def _team_expense_rule_matches(
    doc: EvalDocument,
    rule: TeamExpenseRule,
    *,
    amount: float | None,
) -> bool:
    desc = " ".join(doc.lines).lower()
    merchant = doc.vendor.lower()
    match_on = rule.match_on
    if match_on.description_contains:
        if not _contains_any_token(desc, match_on.description_contains):
            return False
    if match_on.merchant_contains:
        if not _contains_any_token(merchant, match_on.merchant_contains):
            return False
    if match_on.channel_equals:
        channel = doc.capture_channel or infer_capture_channel(doc.email_from)
        if not channel_rule_matches(match_on.channel_equals, channel):
            return False
    if amount is not None:
        if match_on.amount_min is not None and amount < match_on.amount_min:
            return False
        if match_on.amount_max is not None and amount > match_on.amount_max:
            return False
    return True


def match_team_expense_rule(
    doc: EvalDocument,
    rules: list[TeamExpenseRule],
    *,
    amount: float | None = None,
) -> TeamExpenseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=True):
        if _team_expense_rule_matches(doc, rule, amount=amount):
            return rule
    return None


def match_disabled_team_expense_rule(
    doc: EvalDocument,
    rules: list[TeamExpenseRule],
    *,
    amount: float | None = None,
) -> TeamExpenseRule | None:
    for rule in _iter_category_rules(rules, enabled_only=False):
        if _team_expense_rule_matches(doc, rule, amount=amount):
            return rule
    return None


def resolve_category_rule_hit(
    doc: EvalDocument,
    config: RuleBookConfigPayload,
    *,
    amount: float | None = None,
    enabled_only: bool = True,
) -> CategoryRuleHit | None:
    """Architecture §2.1: purchase → expense → team; first match wins."""
    if enabled_only:
        purchase = match_purchase_rule(doc, config.purchase_rules)
        if purchase:
            return CategoryRuleHit(label=purchase.name, kind="Purchase")
        expense = match_expense_rule(doc, config.expense_rules)
        if expense:
            return CategoryRuleHit(label=expense.name, kind="Expense")
        team = match_team_expense_rule(doc, config.team_expense_rules, amount=amount)
        if team:
            return CategoryRuleHit(label=team.name, kind="Team")
        return None

    purchase = match_disabled_purchase_rule(doc, config.purchase_rules)
    if purchase:
        return CategoryRuleHit(label=purchase.name, kind="Purchase")
    expense = match_disabled_expense_rule(doc, config.expense_rules)
    if expense:
        return CategoryRuleHit(label=expense.name, kind="Expense")
    team = match_disabled_team_expense_rule(doc, config.team_expense_rules, amount=amount)
    if team:
        return CategoryRuleHit(label=team.name, kind="Team")
    return None


def detect_vendor(
    doc: EvalDocument,
    masters: list[VendorMaster],
    config: VendorDetectionConfig,
    *,
    account_number: str | None = None,
) -> VendorMatch:
    from app.services.vendor_detection import score_vendor_match

    weights = config.weights
    threshold = float(config.threshold)
    best = VendorMatch(vendor=None, confidence=0.0)
    bank_account = doc.bank_account or account_number

    for master in masters:
        score = score_vendor_match(
            vendor_name=doc.vendor,
            abn=doc.abn,
            billing_address=doc.address,
            bank_bsb=doc.bank_bsb,
            bank_account=bank_account,
            master=master,
            weights=weights,
        )
        if score > best.confidence:
            best = VendorMatch(
                vendor=master if score >= threshold else None,
                confidence=score,
            )

    if best.confidence < threshold:
        return VendorMatch(vendor=None, confidence=best.confidence)
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
        category_rule = resolve_category_rule_hit(doc, config, enabled_only=True)
        category_disabled = None
        if category_rule is None:
            category_disabled = resolve_category_rule_hit(doc, config, enabled_only=False)
        matched = vendor.confidence >= config.vendor_detection_config.threshold
        rows.append(
            LiveEvalRow(
                doc=doc,
                email_rule=email_rule,
                email_rule_disabled=email_disabled,
                vendor=vendor,
                category_rule=category_rule,
                category_rule_disabled=category_disabled,
                matched=matched,
            )
        )
    return rows
