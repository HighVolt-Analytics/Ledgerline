import {
  APPROVAL_MODE_OPTIONS,
  applyPlaybookChange,
  approvalModeLabel,
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
    parts.push(`approve below $${approval.autoApproveBelow}`);
  }
  if (approval.requireApprovalForUnmatched) {
    parts.push("hold when unmatched");
  }
  if (approval.requireApprovalForUnverifiedCounterparty) {
    parts.push("hold when counterparty unverified");
  }
  return parts.join(" · ");
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
  const presetMatch = playbookPresetForProfile(profile).matchMode;
  const matchDiffersFromPreset = match.mode !== presetMatch;
  const presetRouteIncompatible = isProfilePresetMatchRouteIncompatible(draft);

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
          >
            {APPROVAL_MODE_OPTIONS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-3 rounded-md border border-border/70 bg-muted/20 p-3">
        <p className="text-[11px] font-medium text-muted-foreground">Risk-based approval (opt-in)</p>
        <p className="text-[11px] text-muted-foreground">
          Amount threshold is compared to invoice total in the document&apos;s own currency (no FX
          conversion). Leave empty and switches off to preserve legacy behavior.
        </p>
        <FieldLabel label="Require approval at/above ($)">
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
          <span>
            Require approval when no PO/SO match evidence exists (resolved tier is none), even if
            match mode is &quot;none&quot; and approval is touchless.
          </span>
        </label>
        <label className="flex items-start gap-2 text-xs">
          <Switch
            checked={Boolean(approval.requireApprovalForUnverifiedCounterparty)}
            disabled={disabled}
            onCheckedChange={(checked) =>
              updateApprovalPolicy({ requireApprovalForUnverifiedCounterparty: checked })
            }
          />
          <span>
            Require approval when vendor/customer is not yet an established master record.
          </span>
        </label>
      </div>
    </div>
  );
}
