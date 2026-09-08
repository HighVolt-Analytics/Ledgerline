import type { ChartOfAccountRow } from "@/api/types";
import {
  ledgerExistsInCoa,
  ledgerHasSubLedgerCatalog,
  subLedgerExistsInCoa,
} from "@/lib/coaAccountOptions";
import { suggestedLedgerForPlaybookProfile } from "@/lib/documentTypeGlDefaults";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type PostToConfigWarning = {
  id: string;
  message: string;
};

export function documentTypeRequiresPostTo(
  docType: Pick<DocumentTypeDefinition, "posting" | "teamExpenseKind">
): boolean {
  if ((docType.posting ?? "").trim().toLowerCase() === "no") return false;
  // Advance requisitions post Dr employee advance / Cr settlement — no expense ledger.
  if ((docType.teamExpenseKind ?? "").trim() === "advance_requisition") return false;
  return true;
}

export function hasValidPostTo(
  docType: Pick<DocumentTypeDefinition, "posting" | "postTo" | "teamExpenseKind">,
  accounts: ChartOfAccountRow[]
): boolean {
  if (!documentTypeRequiresPostTo(docType)) return true;
  const ledger = docType.postTo?.ledger?.trim() ?? "";
  if (!ledger) return false;
  return ledgerExistsInCoa(ledger, accounts);
}

export function postToConfigWarnings(
  docType: DocumentTypeDefinition,
  accounts: ChartOfAccountRow[]
): PostToConfigWarning[] {
  const warnings: PostToConfigWarning[] = [];
  if (!documentTypeRequiresPostTo(docType)) return warnings;

  const ledger = docType.postTo?.ledger?.trim() ?? "";
  if (!ledger) {
    warnings.push({
      id: "post-to-required",
      message:
        "Post to ledger is required for transactional types — pick an account from your chart of accounts.",
    });
    return warnings;
  }

  if (!ledgerExistsInCoa(ledger, accounts)) {
    warnings.push({
      id: "post-to-not-in-coa",
      message:
        "Selected ledger is not in your chart of accounts — update Settings or pick a valid account.",
    });
  }

  const subLedger = docType.postTo?.subLedger?.trim() ?? "";
  if (
    subLedger &&
    ledgerExistsInCoa(ledger, accounts) &&
    ledgerHasSubLedgerCatalog(ledger, accounts) &&
    !subLedgerExistsInCoa(ledger, subLedger, accounts)
  ) {
    warnings.push({
      id: "post-to-sub-ledger-not-in-coa",
      message:
        "Sub-ledger is not defined under this ledger in chart of accounts — pick a valid sub-ledger or update Settings.",
    });
  }

  const suggested = suggestedLedgerForPlaybookProfile(docType.playbookProfile);
  if (suggested && !ledger && accounts.length > 0) {
    const resolved = accounts.some((row) => row.name.toLowerCase() === suggested.toLowerCase());
    if (!resolved) {
      warnings.push({
        id: "post-to-suggestion-missing",
        message: `Suggested account "${suggested}" is not in your chart of accounts.`,
      });
    }
  }

  return warnings;
}

export function postToMissingOnCard(
  docType: DocumentTypeDefinition,
  accounts: ChartOfAccountRow[]
): boolean {
  return documentTypeRequiresPostTo(docType) && !hasValidPostTo(docType, accounts);
}
