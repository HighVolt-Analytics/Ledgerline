import { Fragment, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageCircle,
  Plus,
  UserCircle,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/context/ToastContext";
import {
  useCreateEmployeeMaster,
  useDeleteEmployeeMaster,
  useEmployeeMasters,
  useUpdateEmployeeMaster,
} from "@/hooks/useMasterData";
import { cn } from "@/lib/cn";
import { fmtAud } from "@/lib/v4MockData";
import { RECENT_CLAIM_VALIDATIONS } from "@/lib/v4RuleBookMockData";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";
import { ChannelBadge } from "@/components/team-expenses/ExpenseBadges";
import { BudgetProgressBar } from "./BudgetProgressBar";
import { EmployeeDetailPanel } from "./EmployeeDetailPanel";

const SAVE_DEBOUNCE_MS = 600;

function StatusDot({ status }: { status: string }) {
  const tone: Record<string, string> = {
    Active: "bg-[hsl(var(--chart-1))]",
    "Pending verification": "bg-destructive",
    Suspended: "bg-destructive",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
      <span className={cn("h-2 w-2 rounded-full shrink-0", tone[status] ?? "bg-muted-foreground")} />
      {status}
    </span>
  );
}

export function EmployeesTab() {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [bankMasked, setBankMasked] = useState(true);
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const { data: employees = [], isLoading } = useEmployeeMasters();
  const createMutation = useCreateEmployeeMaster();
  const updateMutation = useUpdateEmployeeMaster();
  const deleteMutation = useDeleteEmployeeMaster();

  useEffect(() => {
    const timers = saveTimers.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const update = (id: string, patch: Partial<EmployeeMaster>) => {
    const existing = saveTimers.current.get(id);
    if (existing) clearTimeout(existing);
    saveTimers.current.set(
      id,
      setTimeout(() => {
        updateMutation.mutate(
          { id, patch },
          {
            onError: (err) =>
              toast({
                title: "Could not save employee",
                description: err instanceof Error ? err.message : "Save failed",
                variant: "destructive",
              }),
          }
        );
        saveTimers.current.delete(id);
      }, SAVE_DEBOUNCE_MS)
    );
  };

  const addEmployee = () => {
    createMutation.mutate(
      {
        name: "New employee",
        whatsappNumber: "+61 ",
        bank: { accountNumber: "", accountName: "", bankName: "" },
        budget: { monthly: 500, quarterly: 1200, annual: 4500, categories: [] },
        ytdSpent: 0,
        mtdSpent: 0,
        qtdSpent: 0,
        claimCount: 0,
        lastClaim: "—",
        status: "Pending verification",
      },
      {
        onSuccess: (created) => {
          setExpandedId(created.id);
          toast({ title: "Employee created" });
        },
        onError: (err) =>
          toast({
            title: "Could not create employee",
            description: err instanceof Error ? err.message : "Create failed",
            variant: "destructive",
          }),
      }
    );
  };

  const remove = (id: string) => {
    deleteMutation.mutate(id, {
      onSuccess: () => {
        if (expandedId === id) setExpandedId(null);
        toast({ title: "Employee removed" });
      },
      onError: (err) =>
        toast({
          title: "Could not remove employee",
          description: err instanceof Error ? err.message : "Delete failed",
          variant: "destructive",
        }),
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading employee masters…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Define employees who can submit claims via WhatsApp or email, with budgets and bank accounts
          for reimbursement.
        </p>
        <Button
          size="sm"
          onClick={addEmployee}
          disabled={createMutation.isPending}
          data-testid="button-new-employee"
        >
          <Plus className="h-4 w-4 mr-1" /> New Employee
        </Button>
      </div>

      <Card className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border text-left">
                <th className="px-3 py-2 font-medium">Employee</th>
                <th className="px-3 py-2 font-medium">WhatsApp</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium w-44">MTD / Monthly</th>
                <th className="px-3 py-2 font-medium">Last claim</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((emp) => {
                const open = expandedId === emp.id;
                return (
                  <Fragment key={emp.id}>
                    <tr
                      className="row-band border-b border-border/60 cursor-pointer hover:bg-muted/40"
                      onClick={() => setExpandedId(open ? null : emp.id)}
                      data-testid={`employee-row-${emp.id}`}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          {open ? (
                            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          )}
                          <UserCircle className="h-4 w-4 text-muted-foreground shrink-0" />
                          <span className="font-medium">{emp.name}</span>
                        </div>
                        <span className="text-[11px] text-muted-foreground ml-9">{emp.role}</span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                        {emp.whatsappNumber}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground max-w-[180px] truncate">
                        {emp.email || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={emp.status} />
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs whitespace-nowrap">
                            {fmtAud(emp.mtdSpent)} / {fmtAud(emp.budget.monthly)}
                          </span>
                        </div>
                        <div className="mt-1">
                          <BudgetProgressBar value={emp.mtdSpent} max={emp.budget.monthly} />
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                        {emp.lastClaim}
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={6} className="p-0 border-b border-border">
                          <EmployeeDetailPanel
                            emp={emp}
                            onChange={(patch) => update(emp.id, patch)}
                            onRemove={() => remove(emp.id)}
                            masked={bankMasked}
                            onToggleMask={() => setBankMasked((m) => !m)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden" data-testid="recent-claim-validations">
        <div className="p-3 border-b border-border">
          <h3 className="text-sm font-semibold">Recent claim validations</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border text-left">
                <th className="px-3 py-2 font-medium">Employee</th>
                <th className="px-3 py-2 font-medium text-right">Amount</th>
                <th className="px-3 py-2 font-medium">Channel</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {RECENT_CLAIM_VALIDATIONS.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-xs text-muted-foreground">
                    No recent claims for this organisation.
                  </td>
                </tr>
              ) : (
                RECENT_CLAIM_VALIDATIONS.map((claim) => (
                  <tr key={claim.id} className="row-band border-b border-border/60">
                    <td className="px-3 py-2 font-medium">{claim.employee}</td>
                    <td className="px-3 py-2 text-right tnum">{fmtAud(claim.amount)}</td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1">
                        <MessageCircle className="h-3.5 w-3.5 text-muted-foreground" />
                        <ChannelBadge channel={claim.channel} />
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        {claim.outcome === "approved" && (
                          <Check className="h-4 w-4 text-[hsl(var(--chart-1))]" />
                        )}
                        {claim.outcome === "warning" && (
                          <AlertCircle className="h-4 w-4 text-[hsl(43_74%_49%)]" />
                        )}
                        {claim.outcome === "rejected" && (
                          <X className="h-4 w-4 text-destructive" />
                        )}
                        <span className="text-xs text-muted-foreground">{claim.reason}</span>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
