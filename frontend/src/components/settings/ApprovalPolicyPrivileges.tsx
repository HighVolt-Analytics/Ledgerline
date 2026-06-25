import { useEffect, useState } from "react";
import { ChevronRight, Lock, Plus, Unlock } from "lucide-react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  APPROVAL_ACTIONS,
  APPROVAL_ROLES,
  DEFAULT_APPROVAL_MATRIX,
  DEFAULT_APPROVAL_RULES,
  type ApprovalAction,
  type ApprovalRole,
  type LocalApprovalPolicy,
} from "@/lib/approvalPolicy";

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

export function ApprovalPolicyPrivileges() {
  const [policy, setPolicy] = useState<LocalApprovalPolicy>({
    locked: false,
    rules: DEFAULT_APPROVAL_RULES,
    matrix: DEFAULT_APPROVAL_MATRIX,
  });
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    void api.getApprovalPolicy().then((p) => setPolicy(p as LocalApprovalPolicy)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const persistPolicy = async (next: LocalApprovalPolicy) => {
    try {
      const saved = await api.putApprovalPolicy(next);
      setPolicy(saved as LocalApprovalPolicy);
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

  const addRule = () => {
    if (policy.locked) return;
    const next: LocalApprovalPolicy = {
      ...policy,
      rules: [
        ...policy.rules,
        { id: `ap-${Date.now()}`, condition: "New condition", approver: "Reviewer" },
      ],
    };
    setPolicy(next);
    void persistPolicy(next);
  };

  const confirmUnlock = async (code: string) => {
    try {
      const updated = await api.unlockApprovalPolicy(code);
      setPolicy(updated as LocalApprovalPolicy);
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
        Policy and privilege matrix are saved per organisation. Edits are audited; approve,
        reject, and post actions enforce the matrix for each role.
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">Approval rules</h3>
          <Button
            variant="outline"
            size="sm"
            onClick={addRule}
            disabled={policy.locked}
            data-testid="button-add-rule"
          >
            <Plus className="h-4 w-4 mr-1" />
            Add rule
          </Button>
        </div>
        <div className="space-y-2">
          {policy.rules.map((rule) => (
            <div
              key={rule.id}
              className="flex items-center gap-3 text-sm border-b border-border/60 pb-2 last:border-0"
              data-testid={`rule-${rule.id}`}
            >
              <Badge variant="outline" className="shrink-0">
                IF
              </Badge>
              <span className="flex-1">{rule.condition}</span>
              <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
              <Badge className="bg-primary/15 text-primary border-0 shrink-0 hover:bg-primary/15">
                {rule.approver}
              </Badge>
            </div>
          ))}
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
              Role-based permissions across the approval workflow.
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
              onClick={() => setPolicy((p) => ({ ...p, locked: true }))}
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
                <th className="px-3 py-2.5 text-left font-medium w-[120px]">Role</th>
                {APPROVAL_ACTIONS.map((action) => (
                  <th
                    key={action}
                    className="px-2 py-2.5 text-center font-medium whitespace-nowrap min-w-[72px]"
                  >
                    {action}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {APPROVAL_ROLES.map((role) => (
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
                </tr>
              ))}
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
