import type { ChartOfAccountRow } from "@/api/types";
import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

import { Select } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import {
  applyDefaultPostToIfEmpty,
  suggestedLedgerForPlaybookProfile,
} from "@/lib/documentTypeGlDefaults";
import {
  documentTypeRequiresPostTo,
  postToConfigWarnings,
} from "@/lib/documentTypePostToValidation";
import type {
  DocumentTypeDefinition,
  DocumentTypePostTo,
  DocumentTypeTeamExpenseKind,
} from "@/lib/v5DocumentTypes";
import {
  TEAM_EXPENSE_KINDS,
  TEAM_EXPENSE_KIND_LABELS,
} from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "@/components/rule-book/AccountBadge";
import { FieldLabel } from "@/components/rule-book/FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "@/components/rule-book/SubLedgerField";

const TEAM_EXPENSE_ROUTE = "Team Expenses";

const TEAM_EXPENSE_KIND_OPTIONS = [
  { value: "", label: "Auto — decide from advance balance" },
  ...TEAM_EXPENSE_KINDS.map((kind) => ({
    value: kind,
    label: TEAM_EXPENSE_KIND_LABELS[kind],
  })),
];

type DocumentTypePostToEditorProps = {
  draft: DocumentTypeDefinition;
  onChange: (postTo: DocumentTypePostTo) => void;
  onChangeTeamExpenseKind?: (kind: DocumentTypeTeamExpenseKind) => void;
  disabled?: boolean;
};

export function DocumentTypePostToEditor({
  draft,
  onChange,
  onChangeTeamExpenseKind,
  disabled,
}: DocumentTypePostToEditorProps) {
  const { options: mainOptions, allAccounts, isLoading } = useCoaAccountOptions({
    includeEmpty: true,
    emptyLabel: documentTypeRequiresPostTo(draft)
      ? "— Select account —"
      : "— Optional —",
  });

  const ledgerExclude = draft.postTo.ledger.trim() ? [draft.postTo.ledger] : [];
  const { options: receivableOptions } = useCoaAccountOptions({
    excludeNames: ledgerExclude,
    includeEmpty: true,
    emptyLabel: "Accounts Receivable (default)",
    enabled: draft.routeTarget === "Sales Management",
  });
  const { options: taxOptions } = useCoaAccountOptions({
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

  const isAdvanceRequisition = draft.teamExpenseKind === "advance_requisition";

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        {isAdvanceRequisition
          ? "Advance requisitions post Dr employee advance / Cr settlement from Team expense posting — no expense ledger is used."
          : documentTypeRequiresPostTo(draft)
            ? "Required for transactional types. Values come from Settings → Chart of accounts."
            : "Optional for non-transactional types. Leave blank if this document does not post to GL."}
      </p>

      {draft.routeTarget === TEAM_EXPENSE_ROUTE && onChangeTeamExpenseKind ? (
        <div className="space-y-2 max-w-2xl">
          <p className="text-[11px] text-muted-foreground">
            An advance request form is always an advance requisition, so pin the kind here. A receipt
            looks the same whether the employee was reimbursed or spent an advance, so leave those on
            Auto and the outstanding advance decides. Reviewers can still change it on the claim.
          </p>
          <FieldLabel label="Claim kind">
            <Select
              value={draft.teamExpenseKind}
              onValueChange={(kind) =>
                onChangeTeamExpenseKind(kind as DocumentTypeTeamExpenseKind)
              }
              options={TEAM_EXPENSE_KIND_OPTIONS}
              disabled={disabled}
              className="w-full"
              size="md"
              data-testid="dt-team-expense-kind"
            />
          </FieldLabel>
        </div>
      ) : null}

      {!isAdvanceRequisition ? (
        <>
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
        </>
      ) : null}

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
  accounts: ChartOfAccountRow[];
}) {
  const warnings = postToConfigWarnings(docType, accounts as ChartOfAccountRow[]);
  const ledger = docType.postTo?.ledger?.trim() ?? "";
  const isSales = docType.routeTarget === "Sales Management";
  const isTeam = docType.routeTarget === TEAM_EXPENSE_ROUTE;
  const isAdvanceRequisition = docType.teamExpenseKind === "advance_requisition";

  if (isAdvanceRequisition) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Uses employee advance + settlement from Team expense posting (no expense ledger).
        </p>
        <p className="text-xs text-muted-foreground">
          Claim kind: {TEAM_EXPENSE_KIND_LABELS.advance_requisition}
        </p>
      </div>
    );
  }

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
      {isTeam ? (
        <p className="text-xs text-muted-foreground">
          Claim kind:{" "}
          {docType.teamExpenseKind
            ? TEAM_EXPENSE_KIND_LABELS[docType.teamExpenseKind]
            : "Auto — from advance balance"}
        </p>
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
