import { useEffect, useState } from "react";
import { Lock, Plus, Trash2, Unlock } from "lucide-react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  APPROVAL_ACTIONS,
  APPROVAL_MATRIX_ASSIGNABLE_ROLES,
  APPROVAL_ROLES,
  DEFAULT_AMOUNT_APPROVAL_TIERS,
  DEFAULT_APPROVAL_MATRIX,
  APPROVE_ACTION_ALIASES,
  DEFAULT_APPROVAL_LIMITS,
  LEGACY_APPROVAL_ROLE_LABELS,
  normalizeAmountApprovalTiers,
  normalizeApprovalLimits,
  type AmountApprovalTierRow,
  type ApprovalAction,
  type ApprovalLimitsByRole,
  type ApprovalMatrixAssignableRole,
  type ApprovalRole,
  type LocalApprovalPolicy,
} from "@/lib/approvalPolicy";

const ROLE_SELECT_OPTIONS = [
  { value: "", label: "—" },
  ...toSelectOptions(APPROVAL_MATRIX_ASSIGNABLE_ROLES),
];

function foldApproveFlags(perms: Record<string, boolean>): Partial<Record<ApprovalAction, boolean>> {
  const out: Partial<Record<ApprovalAction, boolean>> = {};
  for (const action of APPROVAL_ACTIONS) {
    if (action === "Approve") continue;
    if (typeof perms[action] === "boolean") {
      out[action] = perms[action];
    }
  }
  const hadApproveFamily = APPROVE_ACTION_ALIASES.some((key) => key in perms);
  if (hadApproveFamily) {
    out.Approve = APPROVE_ACTION_ALIASES.some((key) => perms[key] === true);
  }
  return out;
}

function normalizeLocalPolicy(raw: LocalApprovalPolicy): LocalApprovalPolicy {
  const remapped: Record<string, Partial<Record<ApprovalAction, boolean>>> = {};
  for (const [role, perms] of Object.entries(raw.matrix ?? {})) {
    const label = LEGACY_APPROVAL_ROLE_LABELS[role] ?? role;
    remapped[label] = foldApproveFlags(perms as Record<string, boolean>);
  }
  const matrix = {} as Record<ApprovalRole, Record<ApprovalAction, boolean>>;
  for (const role of APPROVAL_ROLES) {
    matrix[role] = {
      ...DEFAULT_APPROVAL_MATRIX[role],
      ...(remapped[role] ?? {}),
    };
  }
  return {
    locked: Boolean(raw.locked),
    matrix,
    approval_limits: normalizeApprovalLimits(
      (raw as LocalApprovalPolicy & { approval_limits?: ApprovalLimitsByRole }).approval_limits
    ),
    amount_approval_tiers: normalizeAmountApprovalTiers(raw.amount_approval_tiers),
  };
}

function UnlockPolicyDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (code: string) => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setCode("");
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 w-full max-w-sm rounded-lg border border-border bg-background p-6 shadow-lg"
      >
        <h4 className="text-sm font-semibold mb-2">Unlock privilege matrix</h4>
        <p className="text-sm text-muted-foreground mb-3">
          Enter the 6-digit administrator code to edit role privileges.
        </p>
        <Input
          value={code}
          onChange={(e) => {
            setCode(e.target.value.replace(/\D/g, "").slice(0, 6));
            setError(null);
          }}
          placeholder="000000"
          className="tnum text-center text-lg tracking-[0.4em] mb-2"
          maxLength={6}
          data-testid="input-unlock-code"
        />
        {error && <p className="text-xs text-destructive mb-2">{error}</p>}
        <Button
          className="w-full"
          data-testid="button-confirm-unlock"
          onClick={() => {
            if (code.length === 6 && /^\d{6}$/.test(code)) {
              onConfirm(code);
              return;
            }
            setError("Enter the 6-digit unlock code.");
          }}
        >
          Unlock
        </Button>
      </div>
    </div>
  );
}

type TierAmountDrafts = Record<string, { min: string; max: string }>;

function draftsFromTiers(tiers: AmountApprovalTierRow[]): TierAmountDrafts {
  return Object.fromEntries(
    tiers.map((t) => [
      t.id,
      {
        min: String(t.min_amount),
        max: t.max_amount == null ? "" : String(t.max_amount),
      },
    ])
  );
}

function parseRoleSelect(value: string): ApprovalMatrixAssignableRole | null {
  if (!value) return null;
  return (APPROVAL_MATRIX_ASSIGNABLE_ROLES as readonly string[]).includes(value)
    ? (value as ApprovalMatrixAssignableRole)
    : null;
}

export function ApprovalPolicyPrivileges() {
  const [policy, setPolicy] = useState<LocalApprovalPolicy>({
    locked: false,
    matrix: DEFAULT_APPROVAL_MATRIX,
    approval_limits: { ...DEFAULT_APPROVAL_LIMITS },
    amount_approval_tiers: DEFAULT_AMOUNT_APPROVAL_TIERS.map((t) => ({ ...t })),
  });
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [limitDrafts, setLimitDrafts] = useState<Record<ApprovalRole, string>>(
    () =>
      Object.fromEntries(APPROVAL_ROLES.map((role) => [role, ""])) as Record<
        ApprovalRole,
        string
      >
  );
  const [tierAmountDrafts, setTierAmountDrafts] = useState<TierAmountDrafts>(() =>
    draftsFromTiers(DEFAULT_AMOUNT_APPROVAL_TIERS)
  );

  const syncDraftsFromPolicy = (next: LocalApprovalPolicy) => {
    setLimitDrafts(
      Object.fromEntries(
        APPROVAL_ROLES.map((role) => [
          role,
          next.approval_limits[role] == null ? "" : String(next.approval_limits[role]),
        ])
      ) as Record<ApprovalRole, string>
    );
    setTierAmountDrafts(draftsFromTiers(next.amount_approval_tiers));
  };

  useEffect(() => {
    void api
      .getApprovalPolicy()
      .then((p) => {
        const next = normalizeLocalPolicy(p as LocalApprovalPolicy);
        setPolicy(next);
        syncDraftsFromPolicy(next);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const persistPolicy = async (next: LocalApprovalPolicy) => {
    try {
      const saved = await api.putApprovalPolicy(next);
      const normalized = normalizeLocalPolicy(saved as LocalApprovalPolicy);
      setPolicy(normalized);
      syncDraftsFromPolicy(normalized);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to save policy");
    }
  };

  const togglePrivilege = (role: ApprovalRole, action: ApprovalAction) => {
    if (policy.locked) return;
    const next: LocalApprovalPolicy = {
      ...policy,
      matrix: {
        ...policy.matrix,
        [role]: { ...policy.matrix[role], [action]: !policy.matrix[role][action] },
      },
    };
    setPolicy(next);
    void persistPolicy(next);
  };

  const commitApprovalLimit = (role: ApprovalRole) => {
    if (policy.locked || !policy.matrix[role].Approve) return;
    const raw = limitDrafts[role].trim().replace(/,/g, "");
    let nextLimit: number | null = null;
    if (raw !== "") {
      const num = Number(raw);
      if (!Number.isFinite(num) || num < 0) {
        setToast("Approval limit must be a non-negative number");
        setLimitDrafts((d) => ({
          ...d,
          [role]:
            policy.approval_limits[role] == null
              ? ""
              : String(policy.approval_limits[role]),
        }));
        return;
      }
      nextLimit = num;
    }
    if (nextLimit === policy.approval_limits[role]) return;
    const next: LocalApprovalPolicy = {
      ...policy,
      approval_limits: { ...policy.approval_limits, [role]: nextLimit },
    };
    setPolicy(next);
    void persistPolicy(next);
  };

  const commitTierAmounts = (tierId: string) => {
    if (policy.locked) return;
    const draft = tierAmountDrafts[tierId];
    if (!draft) return;
    const minRaw = draft.min.trim().replace(/,/g, "");
    const maxRaw = draft.max.trim().replace(/,/g, "");
    const minNum = minRaw === "" ? 0 : Number(minRaw);
    if (!Number.isFinite(minNum) || minNum < 0) {
      setToast("Minimum amount must be a non-negative number");
      const row = policy.amount_approval_tiers.find((t) => t.id === tierId);
      if (row) {
        setTierAmountDrafts((d) => ({
          ...d,
          [tierId]: {
            min: String(row.min_amount),
            max: row.max_amount == null ? "" : String(row.max_amount),
          },
        }));
      }
      return;
    }
    let maxNum: number | null = null;
    if (maxRaw !== "") {
      const parsed = Number(maxRaw);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setToast("Maximum amount must be a non-negative number or empty");
        const row = policy.amount_approval_tiers.find((t) => t.id === tierId);
        if (row) {
          setTierAmountDrafts((d) => ({
            ...d,
            [tierId]: {
              min: String(row.min_amount),
              max: row.max_amount == null ? "" : String(row.max_amount),
            },
          }));
        }
        return;
      }
      maxNum = parsed;
    }
    const row = policy.amount_approval_tiers.find((t) => t.id === tierId);
    if (!row) return;
    if (row.min_amount === minNum && row.max_amount === maxNum) return;
    const nextTiers = policy.amount_approval_tiers.map((t) =>
      t.id === tierId ? { ...t, min_amount: minNum, max_amount: maxNum } : t
    );
    const next: LocalApprovalPolicy = { ...policy, amount_approval_tiers: nextTiers };
    setPolicy(next);
    void persistPolicy(next);
  };

  const updateTierRole = (
    tierId: string,
    field: "approval_1" | "approval_2" | "approval_3",
    value: string
  ) => {
    if (policy.locked) return;
    const role = parseRoleSelect(value);
    const row = policy.amount_approval_tiers.find((t) => t.id === tierId);
    if (!row || row[field] === role) return;
    const nextTiers = policy.amount_approval_tiers.map((t) =>
      t.id === tierId ? { ...t, [field]: role } : t
    );
    const next: LocalApprovalPolicy = { ...policy, amount_approval_tiers: nextTiers };
    setPolicy(next);
    void persistPolicy(next);
  };

  const addTier = () => {
    if (policy.locked) return;
    const last = policy.amount_approval_tiers[policy.amount_approval_tiers.length - 1];
    const nextMin =
      last?.max_amount != null ? last.max_amount + 1 : (last?.min_amount ?? 0) + 1;
    const newRow: AmountApprovalTierRow = {
      id: `tier-${Date.now()}`,
      min_amount: nextMin,
      max_amount: null,
      approval_1: "Manager",
      approval_2: null,
      approval_3: null,
    };
    const next: LocalApprovalPolicy = {
      ...policy,
      amount_approval_tiers: [...policy.amount_approval_tiers, newRow],
    };
    setPolicy(next);
    setTierAmountDrafts((d) => ({
      ...d,
      [newRow.id]: { min: String(newRow.min_amount), max: "" },
    }));
    void persistPolicy(next);
  };

  const removeTier = (tierId: string) => {
    if (policy.locked || policy.amount_approval_tiers.length <= 1) return;
    const nextTiers = policy.amount_approval_tiers.filter((t) => t.id !== tierId);
    const next: LocalApprovalPolicy = { ...policy, amount_approval_tiers: nextTiers };
    setPolicy(next);
    setTierAmountDrafts((d) => {
      const { [tierId]: _, ...rest } = d;
      return rest;
    });
    void persistPolicy(next);
  };

  const confirmUnlock = async (code: string) => {
    try {
      const updated = await api.unlockApprovalPolicy(code);
      const next = normalizeLocalPolicy(updated as LocalApprovalPolicy);
      setPolicy(next);
      syncDraftsFromPolicy(next);
      setUnlockOpen(false);
      setToast("Policy unlocked — privilege matrix is now editable.");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Invalid unlock code");
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {toast}
        </div>
      )}

      <Card className="p-3 border-primary/30 bg-primary/5 text-xs text-muted-foreground">
        Privilege matrix is saved per organisation. Edits are audited; approve, reject, and
        post actions enforce the matrix for each role.
      </Card>

      <Card className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-semibold flex items-center gap-2 flex-wrap">
              Approval Matrix
              {policy.locked && (
                <Badge variant="outline" className="border-destructive/40 text-destructive">
                  <Lock className="h-3 w-3 mr-1" />
                  Locked
                </Badge>
              )}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              When a document waits in Approvals, these amount bands choose which roles must
              approve. Approval 1 and 2 are for the document; Approval 3 is for paying it later.
            </p>
          </div>
          {!policy.locked && (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={addTier}
              data-testid="button-add-approval-tier"
            >
              <Plus className="h-4 w-4 mr-1" />
              Add tier
            </Button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border">
                <th className="px-3 py-2.5 text-left font-medium min-w-[180px]">Amount</th>
                <th className="px-2 py-2.5 text-left font-medium min-w-[140px]">Approval 1</th>
                <th className="px-2 py-2.5 text-left font-medium min-w-[140px]">Approval 2</th>
                <th className="px-2 py-2.5 text-left font-medium min-w-[160px]">
                  Approval 3 (Payment approval)
                </th>
                <th className="px-2 py-2.5 w-10" />
              </tr>
            </thead>
            <tbody>
              {policy.amount_approval_tiers.map((tier) => {
                const draft = tierAmountDrafts[tier.id] ?? {
                  min: String(tier.min_amount),
                  max: tier.max_amount == null ? "" : String(tier.max_amount),
                };
                return (
                  <tr key={tier.id} className="border-b border-border/60 last:border-0">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="text"
                          inputMode="decimal"
                          className="h-8 w-[88px] tnum text-xs"
                          placeholder="Min"
                          value={draft.min}
                          disabled={policy.locked}
                          onChange={(e) => {
                            const next = e.target.value.replace(/[^\d.,]/g, "");
                            setTierAmountDrafts((d) => ({
                              ...d,
                              [tier.id]: { ...draft, min: next },
                            }));
                          }}
                          onBlur={() => commitTierAmounts(tier.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              (e.target as HTMLInputElement).blur();
                            }
                          }}
                          data-testid={`tier-${tier.id}-min`}
                        />
                        <span className="text-muted-foreground text-xs">–</span>
                        <Input
                          type="text"
                          inputMode="decimal"
                          className="h-8 w-[88px] tnum text-xs"
                          placeholder="∞"
                          value={draft.max}
                          disabled={policy.locked}
                          onChange={(e) => {
                            const next = e.target.value.replace(/[^\d.,]/g, "");
                            setTierAmountDrafts((d) => ({
                              ...d,
                              [tier.id]: { ...draft, max: next },
                            }));
                          }}
                          onBlur={() => commitTierAmounts(tier.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              (e.target as HTMLInputElement).blur();
                            }
                          }}
                          data-testid={`tier-${tier.id}-max`}
                        />
                      </div>
                    </td>
                    {(
                      [
                        ["approval_1", "Approval 1"],
                        ["approval_2", "Approval 2"],
                        ["approval_3", "Approval 3"],
                      ] as const
                    ).map(([field, label]) => (
                      <td key={field} className="px-2 py-2.5">
                        <Select
                          size="sm"
                          className="w-full min-w-[132px]"
                          value={tier[field] ?? ""}
                          options={ROLE_SELECT_OPTIONS}
                          disabled={policy.locked}
                          placeholder={label}
                          onValueChange={(v) => updateTierRole(tier.id, field, v)}
                          data-testid={`tier-${tier.id}-${field}`}
                        />
                      </td>
                    ))}
                    <td className="px-2 py-2.5">
                      {!policy.locked && policy.amount_approval_tiers.length > 1 ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                          onClick={() => removeTier(tier.id)}
                          aria-label="Remove tier"
                          data-testid={`tier-${tier.id}-remove`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-semibold flex items-center gap-2 flex-wrap">
              Privilege matrix
              {policy.locked && (
                <Badge variant="outline" className="border-destructive/40 text-destructive">
                  <Lock className="h-3 w-3 mr-1" />
                  Locked
                </Badge>
              )}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              What each role can do. Approval limit is the highest amount that role can approve
              (leave blank for no limit). Limits are editable only when Approve is turned on.
            </p>
          </div>
          {policy.locked ? (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => setUnlockOpen(true)}
              data-testid="button-unlock-policy"
            >
              <Unlock className="h-4 w-4 mr-1" />
              Unlock
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => {
                const next = { ...policy, locked: true };
                setPolicy(next);
                void persistPolicy(next);
              }}
              data-testid="button-lock-policy"
            >
              <Lock className="h-4 w-4 mr-1" />
              Lock policy
            </Button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border">
                <th className="px-3 py-2.5 text-left font-medium w-[160px]">Role</th>
                {APPROVAL_ACTIONS.map((action) => (
                  <th
                    key={action}
                    className="px-2 py-2.5 text-center font-medium whitespace-nowrap min-w-[72px]"
                  >
                    {action}
                  </th>
                ))}
                <th className="px-2 py-2.5 text-center font-medium whitespace-nowrap min-w-[128px]">
                  Approval limit
                </th>
              </tr>
            </thead>
            <tbody>
              {APPROVAL_ROLES.map((role) => {
                const canApprove = policy.matrix[role].Approve;
                const limitActive = canApprove && !policy.locked;
                return (
                  <tr key={role} className="border-b border-border/60 last:border-0">
                    <td className="px-3 py-2.5 font-medium">{role}</td>
                    {APPROVAL_ACTIONS.map((action) => (
                      <td key={action} className="px-2 py-2.5">
                        <div className="flex justify-center">
                          <Switch
                            checked={policy.matrix[role][action]}
                            disabled={policy.locked}
                            onCheckedChange={() => togglePrivilege(role, action)}
                            data-testid={`priv-${role}-${action.replace(/\s+/g, "-")}`}
                          />
                        </div>
                      </td>
                    ))}
                    <td className="px-2 py-2.5">
                      <Input
                        type="text"
                        inputMode="decimal"
                        className="h-8 w-[112px] mx-auto text-center tnum text-xs"
                        placeholder={canApprove ? "Amount" : "—"}
                        value={limitDrafts[role]}
                        disabled={!limitActive}
                        title={
                          canApprove
                            ? "Placeholder approval ceiling for this role"
                            : "Turn on Approve to set an approval limit"
                        }
                        onChange={(e) => {
                          const next = e.target.value.replace(/[^\d.,]/g, "");
                          setLimitDrafts((d) => ({ ...d, [role]: next }));
                        }}
                        onBlur={() => commitApprovalLimit(role)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            (e.target as HTMLInputElement).blur();
                          }
                        }}
                        data-testid={`priv-${role}-Approval-limit`}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <UnlockPolicyDialog
        open={unlockOpen}
        onClose={() => setUnlockOpen(false)}
        onConfirm={confirmUnlock}
      />
    </div>
  );
}
