import { Fragment, useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageCircle,
  Plus,
  Upload,
  UserCircle,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/context/ToastContext";
import { api } from "@/api/client";
import {
  useCreateEmployeeMaster,
  useDeleteEmployeeMaster,
  useEmployeeMasters,
  useImportEmployeeMasters,
  useUpdateEmployeeMaster,
} from "@/hooks/useMasterData";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { cn } from "@/lib/cn";
import { recentClaimValidationsFromInvoices } from "@/lib/routePageAdapters";
import { fmtAud } from "@/lib/v4MockData";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";
import { ChannelBadge } from "@/components/team-expenses/ExpenseBadges";
import { BudgetProgressBar } from "./BudgetProgressBar";
import { EmployeeDetailPanel } from "./EmployeeDetailPanel";
import { EmployeeImportDialog } from "./EmployeeImportDialog";

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
  const [importOpen, setImportOpen] = useState(false);
  const [bankMasked, setBankMasked] = useState(true);
  const [drafts, setDrafts] = useState<Record<string, EmployeeMaster>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());

  const { data: employees = [], isLoading } = useEmployeeMasters();
  const { data: teamClaims = [], isLoading: claimsLoading } = useRoutedInvoices("Team Expenses");
  const recentClaimValidations = useMemo(
    () => recentClaimValidationsFromInvoices(teamClaims, employees, 10),
    [teamClaims, employees]
  );
  const createMutation = useCreateEmployeeMaster();
  const updateMutation = useUpdateEmployeeMaster();
  const deleteMutation = useDeleteEmployeeMaster();
  const importMutation = useImportEmployeeMasters();

  const employeeById = (id: string) => employees.find((e) => e.id === id);

  const getDraft = (emp: EmployeeMaster) => drafts[emp.id] ?? emp;

  const patchDraft = (id: string, patch: Partial<EmployeeMaster>) => {
    const base = drafts[id] ?? employeeById(id);
    if (!base) return;
    setDrafts((prev) => ({ ...prev, [id]: { ...base, ...patch } }));
    setDirtyIds((prev) => new Set(prev).add(id));
  };

  const clearDraft = (id: string) => {
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setDirtyIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const saveDraft = (id: string) => {
    const draft = drafts[id];
    if (!draft) return;
    updateMutation.mutate(
      { id, patch: draft },
      {
        onSuccess: () => {
          clearDraft(id);
          toast({ title: "Employee saved" });
        },
        onError: (err) =>
          toast({
            title: "Could not save employee",
            description: err instanceof Error ? err.message : "Save failed",
            variant: "destructive",
          }),
      }
    );
  };

  const closeEmployee = (id: string) => {
    if (dirtyIds.has(id)) {
      const keep = window.confirm("Discard unsaved employee changes?");
      if (!keep) return;
    }
    clearDraft(id);
    setExpandedId(null);
  };

  const openEmployee = (id: string) => {
    const emp = employeeById(id);
    if (emp && !drafts[id]) {
      setDrafts((prev) => ({ ...prev, [id]: emp }));
    }
    setExpandedId(id);
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
          setDrafts((prev) => ({ ...prev, [created.id]: created }));
          setExpandedId(created.id);
          toast({ title: "Employee created", description: "Edit details, then click Save employee." });
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
    if (!window.confirm("Remove this employee from the rule book?")) return;
    deleteMutation.mutate(id, {
      onSuccess: () => {
        clearDraft(id);
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
          for reimbursement. Edit fields locally, then click Save employee.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setImportOpen(true)}
            data-testid="button-import-employees"
          >
            <Upload className="h-4 w-4 mr-1" /> Import
          </Button>
          <Button
            size="sm"
            onClick={addEmployee}
            disabled={createMutation.isPending}
            data-testid="button-new-employee"
          >
            <Plus className="h-4 w-4 mr-1" /> New Employee
          </Button>
        </div>
      </div>

      <EmployeeImportDialog
        open={importOpen}
        busy={importMutation.isPending}
        onClose={() => setImportOpen(false)}
        onDownloadTemplate={(mode) => api.downloadEmployeeImportTemplate(mode)}
        onPreview={(mode, file) => importMutation.mutateAsync({ mode, file, dryRun: true })}
        onImport={async (mode, file) => {
          const result = await importMutation.mutateAsync({ mode, file, dryRun: false });
          toast({
            title: "Import complete",
            description: `${result.created} created, ${result.updated} updated`,
          });
          return result;
        }}
      />

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
                const draft = getDraft(emp);
                const dirty = dirtyIds.has(emp.id);
                return (
                  <Fragment key={emp.id}>
                    <tr
                      className="row-band border-b border-border/60 cursor-pointer hover:bg-muted/40"
                      onClick={() => {
                        if (open) closeEmployee(emp.id);
                        else openEmployee(emp.id);
                      }}
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
                          <span className="font-medium">
                            {dirty ? draft.name : emp.name}
                            {dirty && (
                              <span className="ml-2 text-[10px] text-amber-600 dark:text-amber-400">
                                unsaved
                              </span>
                            )}
                          </span>
                        </div>
                        <span className="text-[11px] text-muted-foreground ml-9">
                          {dirty ? draft.role : emp.role}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                        {dirty ? draft.whatsappNumber : emp.whatsappNumber}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground max-w-[180px] truncate">
                        {(dirty ? draft.email : emp.email) || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={dirty ? draft.status : emp.status} />
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs whitespace-nowrap">
                            {fmtAud(emp.mtdSpent)} /{" "}
                            {fmtAud(dirty ? draft.budget.monthly : emp.budget.monthly)}
                          </span>
                        </div>
                        <div className="mt-1">
                          <BudgetProgressBar
                            value={emp.mtdSpent}
                            max={dirty ? draft.budget.monthly : emp.budget.monthly}
                          />
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
                            emp={draft}
                            onChange={(patch) => patchDraft(emp.id, patch)}
                            masked={bankMasked}
                            onToggleMask={() => setBankMasked((m) => !m)}
                          />
                          <div className="flex items-center justify-between gap-2 px-4 pb-4 bg-muted/20">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                              disabled={deleteMutation.isPending}
                              onClick={(e) => {
                                e.stopPropagation();
                                remove(emp.id);
                              }}
                              data-testid={`remove-employee-${emp.id}`}
                            >
                              Remove employee
                            </Button>
                            <div className="flex items-center gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  closeEmployee(emp.id);
                                }}
                              >
                                Cancel
                              </Button>
                              <Button
                                size="sm"
                                disabled={!dirty || updateMutation.isPending}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  saveDraft(emp.id);
                                }}
                                data-testid={`save-employee-${emp.id}`}
                              >
                                {updateMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  "Save employee"
                                )}
                              </Button>
                            </div>
                          </div>
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
              {claimsLoading ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Loading recent claims…
                    </span>
                  </td>
                </tr>
              ) : recentClaimValidations.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-xs text-muted-foreground">
                    No recent claims for this organisation.
                  </td>
                </tr>
              ) : (
                recentClaimValidations.map((claim) => (
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
