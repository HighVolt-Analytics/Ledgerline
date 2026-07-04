import {
  APPROVAL_MODE_OPTIONS,
  MATCH_MODE_OPTIONS,
  PLAYBOOK_PROFILE_OPTIONS,
  approvalModeLabel,
  effectiveApprovalPolicy,
  effectiveMatchPolicy,
  effectivePlaybookProfile,
  matchModeLabel,
  playbookProfileLabel,
  playbookPresetForProfile,
  type ApprovalMode,
  type MatchMode,
  type PlaybookProfile,
} from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export function PlaybookDetailSection({ docType }: { docType: DocumentTypeDefinition }) {
  const profile = effectivePlaybookProfile(docType);
  const match = effectiveMatchPolicy(docType);
  const approval = effectiveApprovalPolicy(docType);

  const rows = [
    { label: "Profile", value: playbookProfileLabel(profile) },
    { label: "Match", value: matchModeLabel(match.mode) },
    { label: "Approval", value: approvalModeLabel(approval.mode) },
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
  onChange,
  disabled,
}: {
  draft: DocumentTypeDefinition;
  onChange: (next: DocumentTypeDefinition) => void;
  disabled?: boolean;
}) {
  const profile = effectivePlaybookProfile(draft);
  const match = effectiveMatchPolicy(draft);
  const approval = effectiveApprovalPolicy(draft);

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">Playbook profile</label>
        <select
          value={draft.playbookProfile || profile}
          disabled={disabled}
          onChange={(e) => {
            const profile = e.target.value as PlaybookProfile;
            const preset = playbookPresetForProfile(profile);
            onChange({
              ...draft,
              playbookProfile: profile,
              matchPolicy: { mode: preset.matchMode },
              approvalPolicy: { mode: preset.approvalMode },
            });
          }}
          className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:opacity-50"
        >
          {PLAYBOOK_PROFILE_OPTIONS.map((row) => (
            <option key={row.value} value={row.value}>
              {row.label}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-muted-foreground">
          Preset for 3-way match, approval, and supporting-document enforcement. Override below if needed.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-muted-foreground">Match mode</label>
          <select
            value={draft.matchPolicy?.mode ?? match.mode}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...draft,
                matchPolicy: { mode: e.target.value as MatchMode },
              })
            }
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:opacity-50"
          >
            {MATCH_MODE_OPTIONS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-[11px] font-medium text-muted-foreground">Approval mode</label>
          <select
            value={draft.approvalPolicy?.mode ?? approval.mode}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...draft,
                approvalPolicy: { mode: e.target.value as ApprovalMode },
              })
            }
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:opacity-50"
          >
            {APPROVAL_MODE_OPTIONS.map((row) => (
              <option key={row.value} value={row.value}>
                {row.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
