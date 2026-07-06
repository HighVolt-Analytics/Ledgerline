import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

import { Select } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import {
  coaTypesForMainLedger,
  postingRoleForMainLedger,
} from "@/lib/coaAccountOptions";
import {
  applyDefaultPostToIfEmpty,
  suggestedLedgerForPlaybookProfile,
} from "@/lib/documentTypeGlDefaults";
import {
  documentTypeRequiresPostTo,
  postToConfigWarnings,
} from "@/lib/documentTypePostToValidation";
import type { DocumentTypeDefinition, DocumentTypePostTo } from "@/lib/v5DocumentTypes";
import { AccountBadge } from "@/components/rule-book/AccountBadge";
import { FieldLabel } from "@/components/rule-book/FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "@/components/rule-book/SubLedgerField";

type DocumentTypePostToEditorProps = {
  draft: DocumentTypeDefinition;
  onChange: (postTo: DocumentTypePostTo) => void;
  disabled?: boolean;
};

export function DocumentTypePostToEditor({
  draft,
  onChange,
  disabled,
}: DocumentTypePostToEditorProps) {
  const mainTypes = coaTypesForMainLedger(draft.playbookProfile, draft.routeTarget);
  const mainPostingRole = postingRoleForMainLedger(draft.playbookProfile, draft.routeTarget);
  const { options: mainOptions, allAccounts, hasRealAccounts: hasMainLedgerAccounts, isLoading } = useCoaAccountOptions({
    types: mainTypes,
    postingRole: mainPostingRole,
    includeEmpty: true,
    emptyLabel: documentTypeRequiresPostTo(draft)
      ? "— Select account —"
      : "— Optional —",
  });

  const ledgerExclude = draft.postTo.ledger.trim() ? [draft.postTo.ledger] : [];
  const {
    options: receivableOptions,
    hasRealAccounts: hasReceivableAccounts,
  } = useCoaAccountOptions({
    postingRole: "receivable",
    excludeNames: ledgerExclude,
    includeEmpty: true,
    emptyLabel: "Accounts Receivable (default)",
    enabled: draft.routeTarget === "Sales Management",
  });
  const { options: taxOptions, hasRealAccounts: hasTaxAccounts } = useCoaAccountOptions({
    postingRole: "tax_collected",
    excludeNames: ledgerExclude,
    includeEmpty: true,
    emptyLabel: "GST Collected (default)",
    enabled: draft.routeTarget === "Sales Management",
  });

  const warnings = postToConfigWarnings(draft, allAccounts);
  const suggested = suggestedLedgerForPlaybookProfile(draft.playbookProfile);
  const postTo = draft.postTo;
  const defaultAppliedRef = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    defaultAppliedRef.current = false;
  }, [draft.code]);

  useEffect(() => {
    if (isLoading || defaultAppliedRef.current || !documentTypeRequiresPostTo(draft)) return;
    if (postTo.ledger.trim()) return;
    const next = applyDefaultPostToIfEmpty(
      postTo,
      draft.playbookProfile,
      allAccounts,
      draft.routeTarget
    );
    if (next.ledger !== postTo.ledger) {
      defaultAppliedRef.current = true;
      onChangeRef.current({ ...postTo, ...next });
    }
  }, [
    allAccounts,
    draft.playbookProfile,
    draft.routeTarget,
    draft.code,
    draft.klass,
    draft.posting,
    draft.enabled,
    isLoading,
    postTo.ledger,
    postTo,
  ]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading chart of accounts…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        {documentTypeRequiresPostTo(draft)
          ? "Required for transactional types. Values come from Settings → Chart of accounts."
          : "Optional for non-transactional types. Leave blank if this document does not post to GL."}
      </p>

      {suggested && !postTo.ledger.trim() ? (
        <p className="text-[11px] text-muted-foreground">
          Suggested: <span className="font-medium text-foreground">{suggested}</span>
        </p>
      ) : null}

      {warnings.length > 0 ? (
        <ul className="space-y-1 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-900 dark:text-amber-100">
          {warnings.map((warning) => (
            <li key={warning.id}>{warning.message}</li>
          ))}
        </ul>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 max-w-2xl">
        <div className="space-y-1">
          <FieldLabel label="Ledger (GL)">
            <Select
              value={postTo.ledger}
              onValueChange={(ledger) =>
                onChange({
                  ...postTo,
                  ledger,
                  subLedger: reconcileSubLedgerOnLedgerChange(
                    ledger,
                    postTo.subLedger,
                    allAccounts
                  ),
                })
              }
              options={mainOptions}
              disabled={disabled}
              className="w-full"
              size="md"
              data-testid="dt-post-to-ledger"
            />
          </FieldLabel>
          {mainPostingRole === "revenue" && !hasMainLedgerAccounts ? (
            <p className="text-[10px] text-muted-foreground">
              No revenue account in your chart — add one (type Revenue) in Settings → Chart of accounts.
            </p>
          ) : null}
        </div>
        <FieldLabel label="Sub-ledger">
          <SubLedgerField
            ledger={postTo.ledger}
            value={postTo.subLedger}
            onChange={(subLedger) => onChange({ ...postTo, subLedger })}
            accounts={allAccounts}
            disabled={disabled}
            data-testid="dt-post-to-sub-ledger"
          />
        </FieldLabel>
      </div>

      {draft.routeTarget === "Sales Management" ? (
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground">
            Optional overrides for sales journals. Leave on default unless your chart uses different
            account names for trade debtors or output tax.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 max-w-2xl">
            <div className="space-y-1">
              <FieldLabel label="Receivable account">
                <Select
                  value={postTo.receivableAccount ?? ""}
                  onValueChange={(receivableAccount) => onChange({ ...postTo, receivableAccount })}
                  options={receivableOptions}
                  disabled={disabled}
                  className="w-full"
                />
              </FieldLabel>
              {!hasReceivableAccounts ? (
                <p className="text-[10px] text-muted-foreground">
                  No trade-debtor asset in your chart — using Accounts Receivable default. Add one
                  in Settings → Chart of accounts.
                </p>
              ) : null}
            </div>
            <div className="space-y-1">
              <FieldLabel label="Tax account (collected)">
                <Select
                  value={postTo.taxAccount ?? ""}
                  onValueChange={(taxAccount) => onChange({ ...postTo, taxAccount })}
                  options={taxOptions}
                  disabled={disabled}
                  className="w-full"
                />
              </FieldLabel>
              {!hasTaxAccounts ? (
                <p className="text-[10px] text-muted-foreground">
                  No output-tax liability in your chart — using GST Collected default.
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function salesCounterAccountLabel(value: string | undefined, fallback: string): string {
  const cleaned = (value ?? "").trim();
  return cleaned || `Using default: ${fallback}`;
}

export function DocumentTypePostToDetail({
  docType,
  accounts,
}: {
  docType: DocumentTypeDefinition;
  accounts: { code: string; name: string; type: string }[];
}) {
  const warnings = postToConfigWarnings(docType, accounts);
  const ledger = docType.postTo?.ledger?.trim() ?? "";
  const isSales = docType.routeTarget === "Sales Management";

  if (!documentTypeRequiresPostTo(docType) && !ledger) {
    return <p className="text-sm text-muted-foreground">Optional — not configured.</p>;
  }

  if (!ledger) {
    return (
      <p className="text-sm text-amber-800 dark:text-amber-200">
        Not configured — required before posting.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <AccountBadge account={ledger} />
        {docType.postTo.subLedger ? (
          <span className="text-xs text-muted-foreground">/ {docType.postTo.subLedger}</span>
        ) : null}
      </div>
      {isSales ? (
        <div className="space-y-0.5 text-xs text-muted-foreground">
          <p>Receivable: {salesCounterAccountLabel(docType.postTo.receivableAccount, "Accounts Receivable")}</p>
          <p>Tax (collected): {salesCounterAccountLabel(docType.postTo.taxAccount, "GST Collected")}</p>
        </div>
      ) : null}
      {warnings.length > 0 ? (
        <ul className="text-[11px] text-amber-800 dark:text-amber-200">
          {warnings.map((warning) => (
            <li key={warning.id}>{warning.message}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
