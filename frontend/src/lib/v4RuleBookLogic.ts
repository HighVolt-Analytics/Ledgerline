import type {
  EmailCaptureRule,
  EvalDocument,
  ExpenseRule,
  PurchaseRule,
  RuleCondition,
  RuleConditionGroup,
  SampleEmail,
  VendorDetectionConfig,
  VendorMaster,
} from "./v4RuleBookTypes";

function matchValue(
  haystack: string,
  operator: RuleCondition["operator"],
  needle: string,
  caseSensitive?: boolean
): boolean {
  const a = caseSensitive ? haystack : haystack.toLowerCase();
  const b = caseSensitive ? needle : needle.toLowerCase();
  switch (operator) {
    case "equals":
      return a === b;
    case "not_equals":
      return a !== b;
    case "contains":
      return a.includes(b);
    case "not_contains":
      return !a.includes(b);
    case "starts_with":
      return a.startsWith(b);
    case "ends_with":
      return a.endsWith(b);
    case "regex":
      try {
        return new RegExp(needle, caseSensitive ? "" : "i").test(haystack);
      } catch {
        return false;
      }
    default:
      return false;
  }
}

function evalCondition(email: SampleEmail, cond: RuleCondition): boolean {
  const value = email[cond.field] ?? "";
  return matchValue(value, cond.operator, cond.value, cond.caseSensitive);
}

export function evalConditionGroup(email: SampleEmail, group: RuleConditionGroup): boolean {
  if (group.children.length === 0) return false;
  const results = group.children.map((child) =>
    child.type === "group" ? evalConditionGroup(email, child) : evalCondition(email, child)
  );
  return group.operator === "AND" ? results.every(Boolean) : results.some(Boolean);
}

export function matchEmailCaptureRule(
  email: SampleEmail,
  rules: EmailCaptureRule[]
): EmailCaptureRule | null {
  const sorted = [...rules].filter((r) => r.enabled).sort((a, b) => a.priority - b.priority);
  for (const rule of sorted) {
    if (evalConditionGroup(email, rule.root)) return rule;
  }
  return null;
}

export function docToSampleEmail(doc: EvalDocument): SampleEmail {
  return {
    id: doc.id,
    from: `${doc.vendor.toLowerCase().replace(/\s+/g, "")}@vendor.example`,
    to: "accounts@acme-hospitality.com.au",
    subject: `${doc.invoice_no} — ${doc.vendor}`,
    body: doc.lines.map((l) => l.description).join(" · "),
    attachment_name: `${doc.invoice_no.replace(/\s/g, "")}.pdf`,
    attachment_mime: "application/pdf",
  };
}

export function matchPurchaseRule(
  doc: EvalDocument,
  rules: PurchaseRule[]
): PurchaseRule | null {
  for (const rule of rules) {
    if (!rule.enabled) continue;
    const m = rule.matchOn;
    if (m.poPrefix && doc.po?.startsWith(m.poPrefix)) return rule;
    if (m.poRegex && doc.po) {
      try {
        if (new RegExp(m.poRegex).test(doc.po)) return rule;
      } catch {
        /* ignore */
      }
    }
    if (m.vendorContains && doc.vendor.toLowerCase().includes(m.vendorContains.toLowerCase())) {
      return rule;
    }
  }
  return null;
}

export function matchExpenseRule(doc: EvalDocument, rules: ExpenseRule[]): ExpenseRule | null {
  const desc = doc.lines.map((l) => l.description).join(" ").toLowerCase();
  for (const rule of rules) {
    if (!rule.enabled) continue;
    const m = rule.matchOn;
    if (m.vendorContains && doc.vendor.toLowerCase().includes(m.vendorContains.toLowerCase())) {
      return rule;
    }
    if (m.descriptionContains && desc.includes(m.descriptionContains.toLowerCase())) return rule;
    if (m.docNumberContains && doc.docNumber.toLowerCase().includes(m.docNumberContains.toLowerCase())) {
      return rule;
    }
    if (
      m.referenceContains &&
      (doc.invoice_no || "").toLowerCase().includes(m.referenceContains.toLowerCase())
    ) {
      return rule;
    }
  }
  return null;
}

export type VendorMatch = {
  vendor: VendorMaster | null;
  confidence: number;
};

export type VendorDetectionSample = {
  name: string;
  abn: string;
  bsb?: string;
  accountNumber?: string;
  address?: string;
};

export function detectVendor(
  doc: Pick<EvalDocument, "vendor" | "abn" | "address"> & Pick<VendorDetectionSample, "accountNumber">,
  masters: VendorMaster[],
  config: VendorDetectionConfig
): VendorMatch {
  const weights = config.weights;
  let best: VendorMatch = { vendor: null, confidence: 0 };
  const name = doc.vendor.trim().toLowerCase();

  for (const master of masters) {
    let score = 0;
    const names = [master.name, ...master.aliases].map((n) => n.toLowerCase());
    if (
      name.length >= 4 &&
      names.some((n) => n.length >= 4 && (n.includes(name) || name.includes(n)))
    ) {
      score += weights.name;
    }
    if (doc.abn?.trim() && master.abn !== "PENDING") {
      if (doc.abn.replace(/\s/g, "") === master.abn.replace(/\s/g, "")) score += weights.abn;
    }
    if (doc.accountNumber?.trim() && master.bank.accountNumber) {
      if (
        doc.accountNumber.replace(/\s/g, "") === master.bank.accountNumber.replace(/\s/g, "")
      ) {
        score += weights.bank;
      }
    }
    const addr = (doc.address ?? "").trim().toLowerCase();
    if (addr) {
      const sub = master.billingAddress.suburb.toLowerCase();
      if (
        sub.includes(addr) ||
        master.billingAddress.postcode.includes(addr) ||
        master.billingAddress.street.toLowerCase().includes(addr) ||
        addr.includes(sub)
      ) {
        score += weights.address;
      }
    }
    if (score > best.confidence) best = { vendor: master, confidence: score };
  }
  return best;
}

export function detectVendorFromSample(
  sample: VendorDetectionSample,
  masters: VendorMaster[],
  config: VendorDetectionConfig
): VendorMatch {
  return detectVendor(
    {
      vendor: sample.name,
      abn: sample.abn,
      address: sample.address,
      accountNumber: sample.accountNumber,
    },
    masters,
    config
  );
}

export type LiveEvalRow = {
  doc: EvalDocument;
  emailRule: EmailCaptureRule | null;
  vendor: VendorMatch;
  categoryRule: { label: string; kind: "Purchase" | "Expense" } | null;
  matched: boolean;
};

export function buildLiveEvaluation(
  docs: EvalDocument[],
  rules: {
    emailCaptureRules: EmailCaptureRule[];
    purchaseRules: PurchaseRule[];
    expenseRules: ExpenseRule[];
    vendorMasters: VendorMaster[];
    vendorDetectionConfig: VendorDetectionConfig;
  }
): LiveEvalRow[] {
  return docs.map((doc) => {
    const emailRule = matchEmailCaptureRule(docToSampleEmail(doc), rules.emailCaptureRules);
    const vendor = detectVendor(doc, rules.vendorMasters, rules.vendorDetectionConfig);
    const purchase = matchPurchaseRule(doc, rules.purchaseRules);
    const expense = matchExpenseRule(doc, rules.expenseRules);
    const categoryRule = purchase
      ? { label: purchase.name, kind: "Purchase" as const }
      : expense
        ? { label: expense.name, kind: "Expense" as const }
        : null;
    const matched = vendor.confidence >= rules.vendorDetectionConfig.threshold;
    return { doc, emailRule, vendor, categoryRule, matched };
  });
}
