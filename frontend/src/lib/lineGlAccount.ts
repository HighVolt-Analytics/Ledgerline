import type { ChartOfAccountRow, LineItem } from "@/api/types";
import {
  formatSubLedgerLabel,
  ledgerHasSubLedgerCatalog,
  subLedgersForLedger,
} from "@/lib/coaAccountOptions";

const SOURCE_LABELS: Record<string, string> = {
  llm: "LLM",
  doc_type_default: "Doc type default",
  vendor_default: "Vendor default",
  keyword: "Keyword match",
  manual: "Manual",
};

export function effectiveLineLedger(
  line: Pick<LineItem, "sub_ledger" | "effective_ledger" | "parent_ledger">,
  parentLedger: string
): string {
  const fromApi = line.effective_ledger?.trim();
  if (fromApi) return fromApi;
  const sub = line.sub_ledger?.trim();
  if (sub) return sub;
  const parent = line.parent_ledger?.trim() || parentLedger.trim();
  return parent;
}

export function lineGlSourceLabel(source: string | null | undefined): string {
  const token = (source ?? "").trim();
  if (!token) return "Default";
  return SOURCE_LABELS[token] ?? token;
}

export function lineGlMappingReason(
  line: Pick<LineItem, "gl_mapping_reason" | "gl_mapping_source">,
  parentLedger: string,
  hasCatalog: boolean
): string {
  const reason = line.gl_mapping_reason?.trim();
  if (reason) {
    return `${lineGlSourceLabel(line.gl_mapping_source)}: ${reason}`;
  }
  if (hasCatalog) {
    return `${lineGlSourceLabel(line.gl_mapping_source)}: sub-ledger under ${parentLedger}`;
  }
  return `Main ledger: ${parentLedger}`;
}

export function suggestLineSubLedger(
  line: Pick<LineItem, "description" | "sub_ledger">,
  accounts: ChartOfAccountRow[],
  parentLedger: string
): string {
  const existing = line.sub_ledger?.trim();
  if (existing) return existing;
  const catalogue = subLedgersForLedger(parentLedger, accounts);
  const desc = (line.description ?? "").toLowerCase();
  if (!desc) return "";
  for (const sub of catalogue) {
    const tokens = sub.name
      .replace(/—/g, " ")
      .split(/\s+/)
      .map((token) => token.trim().toLowerCase())
      .filter((token) => token.length >= 3);
    if (tokens.some((token) => desc.includes(token))) {
      return sub.name;
    }
  }
  return "";
}

export function formatLineGlDisplay(
  line: Pick<LineItem, "sub_ledger" | "effective_ledger" | "parent_ledger">,
  parentLedger: string,
  accounts: ChartOfAccountRow[]
): string {
  const effective = effectiveLineLedger(line, parentLedger);
  if (!ledgerHasSubLedgerCatalog(parentLedger, accounts)) {
    return effective;
  }
  const sub = line.sub_ledger?.trim();
  if (sub) {
    const match = subLedgersForLedger(parentLedger, accounts).find((row) => row.name === sub);
    return match ? formatSubLedgerLabel(match) : sub;
  }
  return parentLedger.trim() || effective;
}

export function parentLedgerForLineItems(
  inv: Pick<{ account_name?: string | null }, "account_name">,
  docTypeLedger?: string | null
): string {
  return (docTypeLedger ?? inv.account_name ?? "").trim();
}
