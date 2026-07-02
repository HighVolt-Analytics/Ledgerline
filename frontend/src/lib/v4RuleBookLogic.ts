import type {
  EmailCaptureRule,
  EvalDocument,
  ExpenseRule,
  PurchaseRule,
  SalesRule,
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
  const results = group.children
    .map((child) =>
      child.type === "group"
        ? child.children.length === 0
          ? null
          : evalConditionGroup(email, child)
        : evalCondition(email, child)
    )
    .filter((value): value is boolean => value !== null);
  if (results.length === 0) return false;
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

function poNumberMatchesRule(rule: PurchaseRule, poNumber: string): boolean {
  const m = rule.matchOn;
  if (m.poPrefix && poNumber.startsWith(m.poPrefix)) return true;
  if (m.poRegex) {
    try {
      return new RegExp(m.poRegex).test(poNumber);
    } catch {
      return false;
    }
  }
  return false;
}

export function matchPurchaseRule(
  doc: EvalDocument,
  rules: PurchaseRule[]
): PurchaseRule | null {
  const docType = doc.documentType ?? "invoice";
  if (docType !== "po" && docType !== "grn" && docType !== "invoice") return null;

  const sorted = [...rules]
    .filter((rule) => rule.enabled)
    .sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));

  for (const rule of sorted) {
    const m = rule.matchOn;
    if (!m.poPrefix && !m.poRegex) continue;

    const poNumber = (doc.po ?? "").trim();
    if (!poNumber || !poNumberMatchesRule(rule, poNumber)) continue;

    if (docType === "grn" && !m.grnLinkedToPo) continue;
    if (docType === "invoice" && !m.invoiceReferencesPo) continue;

    if (
      m.vendorContains &&
      !doc.vendor.toLowerCase().includes(m.vendorContains.toLowerCase())
    ) {
      continue;
    }
    return rule;
  }
  return null;
}

export function matchSalesRule(doc: EvalDocument, rules: SalesRule[]): SalesRule | null {
  const desc = doc.lines.map((l) => l.description).join(" ").toLowerCase();
  const customer = doc.vendor.toLowerCase();
  const docNumber = doc.docNumber.toLowerCase();
  const sorted = [...rules]
    .filter((rule) => rule.enabled)
    .sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  for (const rule of sorted) {
    const m = rule.matchOn;
    if (
      !m.customerContains &&
      !m.descriptionContains &&
      !m.docNumberContains &&
      !m.referenceContains
    ) {
      continue;
    }
    if (m.customerContains && !customer.includes(m.customerContains.toLowerCase())) continue;
    if (m.descriptionContains && !desc.includes(m.descriptionContains.toLowerCase())) continue;
    if (
      m.docNumberContains &&
      !docNumber.includes(m.docNumberContains.toLowerCase()) &&
      !(doc.invoice_no || "").toLowerCase().includes(m.docNumberContains.toLowerCase())
    ) {
      continue;
    }
    if (
      m.referenceContains &&
      !(doc.invoice_no || "").toLowerCase().includes(m.referenceContains.toLowerCase())
    ) {
      continue;
    }
    return rule;
  }
  return null;
}

export function matchExpenseRule(doc: EvalDocument, rules: ExpenseRule[]): ExpenseRule | null {
  const desc = doc.lines.map((l) => l.description).join(" ").toLowerCase();
  const sorted = [...rules]
    .filter((rule) => rule.enabled)
    .sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  for (const rule of sorted) {
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

const NAME_FUZZY_MIN_RATIO = 0.82;
const ADDRESS_FUZZY_MIN_RATIO = 0.75;

function normalizeMatchText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function levenshteinRatio(left: string, right: string): number {
  const a = left.trim();
  const b = right.trim();
  if (!a || !b) return 0;
  if (a === b) return 1;
  const short = a.length < b.length ? a : b;
  const long = a.length < b.length ? b : a;
  const prev = Array.from({ length: short.length + 1 }, (_, i) => i);
  for (let i = 1; i <= long.length; i += 1) {
    let prevDiag = prev[0];
    prev[0] = i;
    for (let j = 1; j <= short.length; j += 1) {
      const temp = prev[j];
      const cost = long[i - 1] === short[j - 1] ? 0 : 1;
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, prevDiag + cost);
      prevDiag = temp;
    }
  }
  return 1 - prev[short.length] / Math.max(long.length, short.length);
}

function digitsOnly(value: string | undefined): string {
  return (value ?? "").replace(/\D/g, "");
}

function nameSignalMatches(docName: string, master: VendorMaster): boolean {
  const needle = normalizeMatchText(docName);
  if (needle.length < 4) return false;
  return [master.name, ...master.aliases].some((entry) => {
    const hay = normalizeMatchText(entry);
    return hay.length >= 4 && levenshteinRatio(needle, hay) >= NAME_FUZZY_MIN_RATIO;
  });
}

function addressSignalMatches(docAddress: string, master: VendorMaster): boolean {
  const addr = normalizeMatchText(docAddress);
  if (!addr) return false;
  const postcode = master.billingAddress.postcode.trim();
  const street = normalizeMatchText(master.billingAddress.street);
  const suburb = normalizeMatchText(master.billingAddress.suburb);
  if (postcode && !docAddress.includes(postcode)) return false;
  if (street && (addr.includes(street) || levenshteinRatio(street, addr) >= ADDRESS_FUZZY_MIN_RATIO)) {
    return true;
  }
  if (suburb && levenshteinRatio(suburb, addr) >= ADDRESS_FUZZY_MIN_RATIO) return true;
  if (street && suburb) {
    return levenshteinRatio(`${street} ${suburb}`, addr) >= ADDRESS_FUZZY_MIN_RATIO;
  }
  return false;
}

function bankSignalMatches(
  docBsb: string | undefined,
  docAccount: string | undefined,
  master: VendorMaster
): boolean {
  const masterAccount = digitsOnly(master.bank.accountNumber);
  const docAcct = digitsOnly(docAccount);
  if (!masterAccount || !docAcct || docAcct !== masterAccount) return false;
  const masterBsb = digitsOnly(master.bank.bsb).slice(0, 6);
  const docBsbNorm = digitsOnly(docBsb).slice(0, 6);
  if (masterBsb) return Boolean(docBsbNorm) && docBsbNorm === masterBsb;
  return true;
}

export type VendorDetectionSample = {
  name: string;
  abn: string;
  bsb?: string;
  accountNumber?: string;
  address?: string;
};

export function detectVendor(
  doc: Pick<EvalDocument, "vendor" | "abn" | "address" | "bankBsb" | "bankAccount"> &
    Pick<VendorDetectionSample, "accountNumber">,
  masters: VendorMaster[],
  config: VendorDetectionConfig
): VendorMatch {
  const weights = config.weights;
  const threshold = config.threshold;
  let best: VendorMatch = { vendor: null, confidence: 0 };
  const bankAccount = doc.bankAccount ?? doc.accountNumber;

  for (const master of masters) {
    let score = 0;
    if (doc.vendor.trim() && nameSignalMatches(doc.vendor, master)) score += weights.name;
    const docAbn = digitsOnly(doc.abn);
    const masterAbn = digitsOnly(master.abn);
    if (docAbn && masterAbn && master.abn !== "PENDING" && docAbn === masterAbn) {
      score += weights.abn;
    }
    if (bankSignalMatches(doc.bankBsb, bankAccount, master)) score += weights.bank;
    if (doc.address && addressSignalMatches(doc.address, master)) score += weights.address;
    if (score > best.confidence) {
      best = { vendor: score >= threshold ? master : null, confidence: score };
    }
  }
  if (best.confidence < threshold) return { vendor: null, confidence: best.confidence };
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
      bankBsb: sample.bsb,
      bankAccount: sample.accountNumber,
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
  categoryRule: { label: string; kind: "Sales" | "Purchase" | "Expense" } | null;
  matched: boolean;
};

export function buildLiveEvaluation(
  docs: EvalDocument[],
  rules: {
    emailCaptureRules: EmailCaptureRule[];
    salesRules: SalesRule[];
    purchaseRules: PurchaseRule[];
    expenseRules: ExpenseRule[];
    vendorMasters: VendorMaster[];
    vendorDetectionConfig: VendorDetectionConfig;
  }
): LiveEvalRow[] {
  return docs.map((doc) => {
    const emailRule = matchEmailCaptureRule(docToSampleEmail(doc), rules.emailCaptureRules);
    const vendor = detectVendor(doc, rules.vendorMasters, rules.vendorDetectionConfig);
    const sales = matchSalesRule(doc, rules.salesRules);
    const purchase = matchPurchaseRule(doc, rules.purchaseRules);
    const expense = matchExpenseRule(doc, rules.expenseRules);
    const categoryRule = sales
      ? { label: sales.name, kind: "Sales" as const }
      : purchase
        ? { label: purchase.name, kind: "Purchase" as const }
        : expense
          ? { label: expense.name, kind: "Expense" as const }
          : null;
    const matched = vendor.confidence >= rules.vendorDetectionConfig.threshold;
    return { doc, emailRule, vendor, categoryRule, matched };
  });
}
