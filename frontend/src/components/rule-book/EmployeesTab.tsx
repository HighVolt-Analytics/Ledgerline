import { Fragment, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Mail,
  Plus,
  Upload,
  UserCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CreationsEmployeesTabSkeleton } from "@/components/skeleton/PageSkeletons";
import { useToast } from "@/context/ToastContext";
import { api } from "@/api/client";
import {
  useCreateEmployeeMaster,
  useDeleteEmployeeMaster,
  useEmployeeMasters,
  useImportEmployeeMasters,
  useSendEmployeeMasterConfirmation,
  useUpdateEmployeeMaster,
} from "@/hooks/useMasterData";
import { useRuleBookTeamExpensePosting } from "@/hooks/useRuleBookConfig";
import { ledgerExistsInCoa } from "@/lib/coaAccountOptions";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import { cn } from "@/lib/cn";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";
import { EmployeeDetailPanel } from "./EmployeeDetailPanel";
import { EmployeeImportDialog } from "./EmployeeImportDialog";
import { usePermissions } from "@/hooks/usePermissions";

const EMPLOYEE_SECTIONS = [
  { value: "pending", label: "Pending", testid: "tab-employees-pending" },
  { value: "list", label: "Employee list", testid: "tab-employees-list" },
] as const;

type EmployeeSection = (typeof EMPLOYEE_SECTIONS)[number]["value"];

function cellText(value?: string | null) {
  return value?.trim() ?? "";
}

function isPendingEmployee(emp: EmployeeMaster) {
  return emp.status === "Pending verification";
}

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
  const { permissions } = usePermissions();
  const canRevealBank = permissions?.can_reveal_bank === true;
  const [section, setSection] = useState<EmployeeSection>("list");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pinToTopId, setPinToTopId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [revealBank, setRevealBank] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, EmployeeMaster>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());

  const { data: employees = [], isLoading } = useEmployeeMasters(true, revealBank && canRevealBank);
  const bankMasked = !revealBank;
  const toggleRevealBank = () => {
    if (!canRevealBank) return;
    setRevealBank((current) => !current);
    setDrafts({});
    setDirtyIds(new Set());
  };
  const { data: posting } = useRuleBookTeamExpensePosting(!isLoading);
  const { data: coaAccounts = [] } = useChartOfAccounts(!isLoading);
  const createMutation = useCreateEmployeeMaster();
  const updateMutation = useUpdateEmployeeMaster();
  const deleteMutation = useDeleteEmployeeMaster();
  const importMutation = useImportEmployeeMasters();
  const sendConfirmationMutation = useSendEmployeeMasterConfirmation();

  const sendEmployeeConfirmation = (employee: EmployeeMaster) => {
    sendConfirmationMutation.mutate(employee.id, {
      onSuccess: (result) => {
        toast({
          title: "Confirmation email sent",
          description: result.email ? `Sent to ${result.email}` : undefined,
        });
      },
      onError: (err) =>
        toast({
          title: "Could not send confirmation",
          description: err instanceof Error ? err.message : "Send failed",
          variant: "destructive",
        }),
    });
  };

  const defaultAdvanceParent = useMemo(() => {
    const label = posting?.defaultAdvanceParentLedger?.trim() ?? "";
    if (label && ledgerExistsInCoa(label, coaAccounts)) return label;
    return "";
  }, [coaAccounts, posting?.defaultAdvanceParentLedger]);

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
    if (pinToTopId === id) setPinToTopId(null);
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
        advanceParentLedger: defaultAdvanceParent,
        ytdSpent: 0,
        mtdSpent: 0,
        qtdSpent: 0,
        claimCount: 0,
        lastClaim: "—",
        status: "Pending verification",
      },
      {
        onSuccess: (created) => {
          setSection("list");
          setPinToTopId(created.id);
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
        if (pinToTopId === id) setPinToTopId(null);
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

  const listedEmployees = useMemo(() => {
    if (!pinToTopId) return employees;
    const idx = employees.findIndex((emp) => emp.id === pinToTopId);
    if (idx <= 0) return employees;
    return [employees[idx]!, ...employees.slice(0, idx), ...employees.slice(idx + 1)];
  }, [employees, pinToTopId]);

  const pendingEmployees = useMemo(
    () => employees.filter((emp) => isPendingEmployee(emp) && emp.id !== pinToTopId),
    [employees, pinToTopId]
  );

  const renderEmployeeTable = (rows: EmployeeMaster[], emptyLabel: string) => (
    <Card className="p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground border-b border-border text-left">
              <th className="px-3 py-2 font-medium">Employee</th>
              <th className="px-3 py-2 font-medium">WhatsApp</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Department</th>
              <th className="px-3 py-2 font-medium">Location</th>
              <th className="px-3 py-2 font-medium">Supervisor 1</th>
              <th className="px-3 py-2 font-medium">Supervisor 2</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {emptyLabel}
                </td>
              </tr>
            ) : (
              rows.map((emp) => {
                const open = expandedId === emp.id;
                const draft = getDraft(emp);
                const dirty = dirtyIds.has(emp.id);
                const display = dirty ? draft : emp;
                const role = display.role?.trim();
                return (
                  <Fragment key={emp.id}>
                    <tr
                      className="row-band border-b border-border/60 last:border-0 cursor-pointer hover:bg-muted/40"
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
                            {display.name}
                            {dirty && (
                              <span className="ml-2 text-[10px] ds-warning-text">
                                unsaved
                              </span>
                            )}
                          </span>
                        </div>
                        {role ? (
                          <span className="text-[11px] text-muted-foreground ml-9">{role}</span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                        {cellText(display.whatsappNumber)}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground max-w-[180px] truncate">
                        {cellText(display.email)}
                      </td>
                      <td className="px-3 py-2 text-xs">{cellText(display.department)}</td>
                      <td className="px-3 py-2 text-xs">{cellText(display.location)}</td>
                      <td className="px-3 py-2 text-xs">{cellText(display.supervisor1)}</td>
                      <td className="px-3 py-2 text-xs">{cellText(display.supervisor2)}</td>
                      <td className="px-3 py-2">
                        <StatusDot status={display.status} />
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={8} className="p-0 border-b border-border">
                          <EmployeeDetailPanel
                            emp={draft}
                            onChange={(patch) => patchDraft(emp.id, patch)}
                            masked={bankMasked}
                            onToggleMask={canRevealBank ? toggleRevealBank : undefined}
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
                                disabled={sendConfirmationMutation.isPending}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  sendEmployeeConfirmation(dirty ? draft : emp);
                                }}
                                data-testid={`send-employee-confirmation-${emp.id}`}
                              >
                                {sendConfirmationMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <>
                                    <Mail className="h-3.5 w-3.5 mr-1" />
                                    {emp.confirmationSentAt ? "Resend confirmation" : "Send confirmation"}
                                  </>
                                )}
                              </Button>
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
              })
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );

  if (isLoading) {
    return <CreationsEmployeesTabSkeleton />;
  }

  return (
    <div className="space-y-4">
      <PageTabs
        value={section}
        onChange={(value) => setSection(value as EmployeeSection)}
        data-testid="employees-section-tabs"
        tabs={EMPLOYEE_SECTIONS.map((row) => ({
          value: row.value,
          label:
            row.value === "pending" && pendingEmployees.length > 0
              ? `${row.label} (${pendingEmployees.length})`
              : row.label,
          testid: row.testid,
          secondary: true,
        }))}
      />

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

      <PageTabPanel value="pending" active={section} className="mt-0 space-y-4">
        {renderEmployeeTable(pendingEmployees, "No employees pending verification.")}
      </PageTabPanel>

      <PageTabPanel value="list" active={section} className="mt-0 space-y-4">
        <div className="flex justify-end flex-wrap gap-2">
          {canRevealBank ? (
            <button
              type="button"
              onClick={toggleRevealBank}
              className="text-xs text-muted-foreground hover:text-foreground self-center"
              data-testid="toggle-bank-mask"
            >
              {bankMasked ? "Show bank details" : "Hide bank details"}
            </button>
          ) : null}
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
        {renderEmployeeTable(listedEmployees, "No employees in the list yet.")}
      </PageTabPanel>
    </div>
  );
}
