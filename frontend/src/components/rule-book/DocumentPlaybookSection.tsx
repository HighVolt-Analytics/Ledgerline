import {
  APPROVAL_MODE_OPTIONS,
  applyPlaybookChange,
  approvalModeLabel,
  approvalModeOptionsForEditor,
  effectiveApprovalPolicy,
  effectiveMatchPolicy,
  effectivePlaybookProfile,
  isProfilePresetMatchRouteIncompatible,
  matchModeLabel,
  matchModeOptionsForEditor,
  playbookPresetForProfile,
  playbookProfileLabel,
  playbookProfileOptionsForEditor,
  type ApprovalMode,
  type ApprovalPolicy,
  type MatchMode,
  type PlaybookProfile,
} from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { NumericInput } from "@/components/ui/numeric-input";
import { Switch } from "@/components/ui/switch";
import { FieldLabel } from "./FieldLabel";

function hasRiskApprovalSettings(approval: ApprovalPolicy): boolean {
  return (
    (approval.autoApproveBelow != null && approval.autoApproveBelow > 0) ||
    Boolean(approval.requireApprovalForUnmatched) ||
    Boolean(approval.requireApprovalForUnverifiedCounterparty)
  );
}

function riskApprovalSummary(approval: ApprovalPolicy): string | null {
  if (!hasRiskApprovalSettings(approval)) return null;
  const parts: string[] = [];
  if (approval.autoApproveBelow != null && approval.autoApproveBelow > 0) {
    parts.push(`at/above $${approval.autoApproveBelow}`);
  }
  if (approval.requireApprovalForUnmatched) {
    parts.push("no PO/SO match");
  }
  if (approval.requireApprovalForUnverifiedCounterparty) {
    parts.push("new vendor/customer");
  }
  return parts.join(" · ");
}

function approvalModeHint(mode: ApprovalMode): string {
  return APPROVAL_MODE_OPTIONS.find((row) => row.value === mode)?.hint ?? "";
}

export function PlaybookDetailSection({ docType }: { docType: DocumentTypeDefinition }) {
  const profile = effectivePlaybookProfile(docType);
  const match = effectiveMatchPolicy(docType);
  const approval = effectiveApprovalPolicy(docType);
  const riskSummary = riskApprovalSummary(approval);

  const rows = [
    { label: "Profile", value: playbookProfileLabel(profile) },
    { label: "Match", value: matchModeLabel(match.mode) },
    { label: "Approval", value: approvalModeLabel(approval.mode) },
    ...(riskSummary ? [{ label: "Risk gates", value: riskSummary }] : []),
  ];

  return (
    <dl className="space-y-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-3 text-sm">
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="font-medium text-right text-foreground">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PlaybookPolicyEditor({
  draft,
  documentTypes,
  onChange,
  disabled,
}: {
  draft: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
  onChange: (next: DocumentTypeDefinition) => void;
  disabled?: boolean;
}) {
  const profile = effectivePlaybookProfile(draft);
  const match = effectiveMatchPolicy(draft);
  const approval = effectiveApprovalPolicy(draft);
  const profileOptions = playbookProfileOptionsForEditor(draft);
  const matchOptions = matchModeOptionsForEditor(draft);
  const approvalOptions = approvalModeOptionsForEditor(draft);
  const presetMatch = playbookPresetForProfile(profile).matchMode;
  const matchDiffersFromPreset = match.mode !== presetMatch;
  const presetRouteIncompatible = isProfilePresetMatchRouteIncompatible(draft);
  const showRiskGates = approval.mode !== "no_posting";
  const isTeamRoute = (draft.routeTarget || "").trim() === "Team Expenses";
  const modeHint = approvalModeHint(approval.mode);

  const updateApprovalPolicy = (patch: Partial<ApprovalPolicy>) => {
    onChange({
      ...draft,
      approvalPolicy: {
        ...approval,
        ...patch,
      },
    });
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">Playbook profile</label>
        <select
          value={profile}
          disabled={disabled}
          onChange={(e) => {
            onChange(applyPlaybookChange(draft, e.target.value as PlaybookProfile, documentTypes));
          }}
          className="h-9 w-full rounded-md border border-border bg-field px-2 text-sm disabled:opacity-50"
        >
          {profileOptions.map((row) => (
            <option key={row.value} value={row.value}>
              {row.label}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-muted-foreground">
          Preset for match mode, approval, and supporting-document enforcement. Override below if
          needed.
        </p>
        {presetRouteIncompatible ? (
          <p className="text-[11px] text-amber-600 dark:text-amber-500">
            This profile&apos;s default match mode is not valid on {draft.routeTarget}. Match was
            clamped to {matchModeLabel(match.mode)}.
          </p>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-muted-foreground">Match mode</label>
          <select
            value={match.mode}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...draft,
                matchPolicy: { mode: e.target.value as MatchMode },
              })
            }
            className="h-9 w-full rounded-md border border-border bg-field px-2 text-sm disabled:opacity-50"
          >
            {matchOptions.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
          {matchDiffersFromPreset ? (
            <p className="text-[11px] text-muted-foreground">
              Override: profile preset is {matchModeLabel(presetMatch)}.
            </p>
          ) : null}
        </div>

        <div className="space-y-1">
          <label className="text-[11px] font-medium text-muted-foreground">Approval mode</label>
          <select
            value={approval.mode}
            disabled={disabled}
            onChange={(e) =>
              updateApprovalPolicy({ mode: e.target.value as ApprovalMode })
            }
            className="h-9 w-full rounded-md border border-border bg-field px-2 text-sm disabled:opacity-50"
            data-testid="select-approval-mode"
          >
            {approvalOptions.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-muted-foreground">
            Choose when this document type should wait in the Approvals queue. Who can
            approve is set under Settings → Policy &amp; privileges.
          </p>
          {modeHint ? (
            <p className="text-[11px] text-muted-foreground">{modeHint}</p>
          ) : null}
          {approval.mode === "manager_gate" && !isTeamRoute ? (
            <p className="text-[11px] text-amber-600 dark:text-amber-500">
              Team expense check is only for Team Expenses. On this route, documents will
              always go to Approvals.
            </p>
          ) : null}
          {approval.mode === "touchless_on_clean_match" &&
          (match.mode === "none" || match.mode === "subledger_reconcile") ? (
            <p className="text-[11px] text-amber-600 dark:text-amber-500">
              Match is set to {matchModeLabel(match.mode)}, so there is nothing to auto-match.
              Documents will go to Approvals. Pick &quot;Full DOA approval&quot;, or turn on a
              real match mode if you want touchless on clean match.
            </p>
          ) : null}
        </div>
      </div>

      {showRiskGates ? (
        <div className="space-y-3 rounded-md border border-border/70 bg-muted/20 p-3">
          <p className="text-[11px] font-medium text-muted-foreground">
            Also send for approval when…
          </p>
          <p className="text-[11px] text-muted-foreground">
            Optional extras. Use the same currency as the document. Leave blank / off to use
            Approval mode only.
          </p>
          {approval.mode === "manager_gate" ? (
            <p className="text-[11px] text-muted-foreground">
              Team Expenses also respects the amount threshold on the team rule.
            </p>
          ) : null}
          <FieldLabel label="Total is at or above ($)">
            <NumericInput
              value={approval.autoApproveBelow ?? undefined}
              onValueChange={(value) =>
                updateApprovalPolicy({
                  autoApproveBelow: value == null || value <= 0 ? null : value,
                })
              }
              disabled={disabled}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <label className="flex items-start gap-2 text-xs">
            <Switch
              checked={Boolean(approval.requireApprovalForUnmatched)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                updateApprovalPolicy({ requireApprovalForUnmatched: checked })
              }
            />
            <span>There is no PO or SO match (even if Match mode is None).</span>
          </label>
          <label className="flex items-start gap-2 text-xs">
            <Switch
              checked={Boolean(approval.requireApprovalForUnverifiedCounterparty)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                updateApprovalPolicy({ requireApprovalForUnverifiedCounterparty: checked })
              }
            />
            <span>The vendor or customer is not yet in your master list.</span>
          </label>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Extra approval rules are not used when the mode is &quot;No posting&quot;.
        </p>
      )}
    </div>
  );
}
