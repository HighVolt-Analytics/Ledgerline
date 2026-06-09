import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  ChevronRight,
  Lock,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Unlock,
  X,
} from "lucide-react";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { invId, money } from "@/lib/format";
import { fetchAllApprovals, fetchAllInvoices } from "@/lib/invoices";
import { cn } from "@/lib/cn";

const APPROVAL_POLL_MS = 15_000;
const PROCESSING_POLL_MS = 2_000;
const PROCESSING_TIMEOUT_MS = 60_000;
const API_HINT = " Ensure the API is running on port 8001.";

const COLUMNS = [
  { key: "pending", label: "To review" },
  { key: "awaiting", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
] as const;

type ColumnKey = (typeof COLUMNS)[number]["key"];

const ROLES = ["Admin", "Approver", "Bookkeeper", "Viewer", "Auditor"] as const;
const ACTIONS = [
  "View",
  "Comment",
  "Approve",
  "Reject",
  "Publish",
  "Edit Policy",
  "Manage Users",
] as const;

type Role = (typeof ROLES)[number];
type Action = (typeof ACTIONS)[number];

type PolicyRule = { id: string; condition: string; approver: string };

type LocalApprovalPolicy = {
  locked: boolean;
  rules: PolicyRule[];
  matrix: Record<Role, Record<Action, boolean>>;
};

const DEFAULT_RULES: PolicyRule[] = [
  { id: "ap1", condition: "Invoices > 5,000", approver: "CFO approval" },
  { id: "ap2", condition: "Marketing Expense invoices", approver: "Marketing Lead" },
  { id: "ap3", condition: "Suspense-routed invoices", approver: "Finance Controller" },
  { id: "ap4", condition: "New vendor (first invoice)", approver: "Bookkeeper review" },
];

const DEFAULT_MATRIX: Record<Role, Record<Action, boolean>> = {
  Admin: Object.fromEntries(ACTIONS.map((a) => [a, true])) as Record<Action, boolean>,
  Approver: {
    View: true,
    Comment: true,
    Approve: true,
    Reject: true,
    Publish: true,
    "Edit Policy": false,
    "Manage Users": false,
  },
  Bookkeeper: {
    View: true,
    Comment: true,
    Approve: false,
    Reject: false,
    Publish: false,
    "Edit Policy": false,
    "Manage Users": false,
  },
  Viewer: {
    View: true,
    Comment: false,
    Approve: false,
    Reject: false,
    Publish: false,
    "Edit Policy": false,
    "Manage Users": false,
  },
  Auditor: {
    View: true,
    Comment: true,
    Approve: false,
    Reject: false,
    Publish: false,
    "Edit Policy": false,
    "Manage Users": false,
  },
};

const PIPELINE_STATUSES = new Set([
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
]);

const APPROVAL_QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

const APPROVABLE_STATUSES = new Set(["exception", "rejected", "duplicate_skipped"]);

const PERMANENTLY_DELETABLE = new Set(["rejected", "duplicate_skipped"]);

function columnForInvoice(inv: Invoice): ColumnKey {
  if (inv.status === "rejected" || inv.status === "duplicate_skipped") return "rejected";
  if (inv.status === "processed") return "approved";
  if (inv.status === "exception") return "pending";
  if (PIPELINE_STATUSES.has(inv.status)) return "awaiting";
  return "pending";
}

function docNumber(inv: Invoice): string {
  return inv.invoice_no ?? `DOC-${String(inv.id).padStart(4, "0")}`;
}

async function fetchBoardInvoices(fresh: boolean): Promise<Invoice[]> {
  const [approvals, allInvoices] = await Promise.all([
    fetchAllApprovals(fresh),
    fetchAllInvoices(fresh),
  ]);
  const pipeline = allInvoices.filter((inv) => PIPELINE_STATUSES.has(inv.status));
  const approved = allInvoices.filter((inv) => inv.status === "processed");
  return mergeBoardInvoices(approvals, [...pipeline, ...approved]);
}

function mergeBoardInvoices(approvals: Invoice[], pipeline: Invoice[]): Invoice[] {
  const byId = new Map<number, Invoice>();
  for (const inv of pipeline) byId.set(inv.id, inv);
  for (const inv of approvals) byId.set(inv.id, inv);
  return [...byId.values()];
}

async function watchProcessingUntilIdle(
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawRunning = false;
  while (Date.now() < deadline) {
    await refresh();
    const status = await api.getProcessingStatus();
    if (status.state === "running" || status.active_tasks > 0) {
      sawRunning = true;
    }
    if (sawRunning && status.state === "idle" && status.active_tasks === 0) {
      await refresh();
      return;
    }
    if (!sawRunning && status.state === "idle" && status.active_tasks === 0) {
      // Give a fast worker one poll cycle; otherwise keep invoice in awaiting.
      await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
      await refresh();
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
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

export function ApprovalsPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"board" | "policy">("board");
  const [policy, setPolicy] = useState<LocalApprovalPolicy>({
    locked: false,
    rules: DEFAULT_RULES,
    matrix: DEFAULT_MATRIX,
  });
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [drawerInvoice, setDrawerInvoice] = useState<Invoice | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEditMode, setDrawerEditMode] = useState(false);

  function openDrawer(inv: Invoice, edit = false) {
    setDrawerInvoice(inv);
    setDrawerEditMode(edit);
    setDrawerOpen(true);
  }
  const [busyId, setBusyId] = useState<number | null>(null);
  const [processingBusy, setProcessingBusy] = useState(false);

  const runProcessing = async () => {
    setProcessingBusy(true);
    setToast(null);
    try {
      await api.triggerProcess();
      await watchProcessingUntilIdle(async () => {
        await load({ silent: true, fresh: true });
      });
      setToast("Processing finished — refresh the board if cards did not move.");
      await load({ fresh: true });
    } catch (e) {
      setToast(
        (e instanceof Error ? e.message : "Processing failed") +
          " Start the Celery worker in backend (see terminal)."
      );
    } finally {
      setProcessingBusy(false);
    }
  };

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    const fresh = options?.fresh ?? !options?.silent;

    const boardResult = await Promise.allSettled([fetchBoardInvoices(fresh)]);

    if (boardResult[0].status === "fulfilled") {
      setInvoices(boardResult[0].value);
      if (!options?.silent) setError(null);
    } else if (!options?.silent) {
      setInvoices([]);
      const reason = boardResult[0].reason;
      setError(
        reason instanceof Error
          ? reason.message + API_HINT
          : "Failed to load approvals" + API_HINT
      );
    }

    if (!options?.silent) setLoading(false);
  }, []);

  useEffect(() => {
    void load();
    void api.getApprovalPolicy().then((p) => setPolicy(p as LocalApprovalPolicy)).catch(() => {});
  }, [load]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, APPROVAL_POLL_MS);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const board = useMemo(() => {
    const cols: Record<ColumnKey, Invoice[]> = {
      pending: [],
      awaiting: [],
      approved: [],
      rejected: [],
    };
    for (const inv of invoices) {
      cols[columnForInvoice(inv)].push(inv);
    }
    return cols;
  }, [invoices]);

  const queueCount = useMemo(
    () => invoices.filter((inv) => APPROVAL_QUEUE_STATUSES.has(inv.status)).length,
    [invoices]
  );

  const approveInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv) return;
    if (!inv.has_stored_file) {
      setToast("Upload a PDF before approving this invoice.");
      return;
    }
    setBusyId(id);
    try {
      const approved = await api.approve(id);
      setInvoices((prev) => {
        const byId = new Map(prev.map((i) => [i.id, i]));
        byId.set(approved.id, approved);
        return [...byId.values()];
      });
      setToast("Invoice queued for processing…");
      await load({ silent: true, fresh: true });
      await api.triggerProcess();
      await watchProcessingUntilIdle(() => load({ silent: true, fresh: true }));
      setToast("Invoice approved — processing complete");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  };

  const rejectInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || (inv.status !== "exception" && inv.status !== "processed")) {
      setToast("This invoice cannot be rejected.");
      return;
    }
    setBusyId(id);
    try {
      await api.reject(id);
      setToast("Invoice rejected — file moved to rejected storage");
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusyId(null);
    }
  };

  const permanentDeleteInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || !PERMANENTLY_DELETABLE.has(inv.status)) {
      setToast("This invoice cannot be permanently deleted.");
      return;
    }
    if (!window.confirm("Do you want to delete it permanently?")) {
      return;
    }
    setBusyId(id);
    try {
      await api.deleteApprovalPermanently(id);
      setInvoices((prev) => prev.filter((i) => i.id !== id));
      if (drawerInvoice?.id === id) {
        setDrawerOpen(false);
        setDrawerInvoice(null);
      }
      setToast("Invoice permanently deleted");
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Permanent delete failed");
    } finally {
      setBusyId(null);
    }
  };

  const persistPolicy = async (next: LocalApprovalPolicy) => {
    try {
      const saved = await api.putApprovalPolicy(next);
      setPolicy(saved as LocalApprovalPolicy);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to save policy");
    }
  };

  const publish = async (inv: Invoice) => {
    if (inv.status !== "processed") {
      setToast("Publish is available for processed invoices only.");
      return;
    }
    setBusyId(inv.id);
    try {
      await api.publishInvoice(inv.id);
      setToast(`Published · ${invId(inv.id)}`);
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setBusyId(null);
    }
  };

  const togglePrivilege = (role: Role, action: Action) => {
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

  if (loading && invoices.length === 0) {
    return (
      <div>
        <PageHeader title="Approvals" subtitle="Review and approve invoices — live data from the API." />
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading approvals…</Card>
      </div>
    );
  }

  if (error && invoices.length === 0) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error}
      </Card>
    );
  }

  if (!loading && queueCount === 0 && board.awaiting.length === 0 && board.approved.length === 0) {
    return (
      <div>
        <PageHeader
          title="Approvals"
          subtitle="Review and approve invoices — live data from the API."
        />
        <EmptyState
          title="Nothing to approve"
          hint="Exception invoices appear here for review. Rejected files are stored under rejected/org/vendor/year/month in Azure."
          action={
            <Link
              to="/inbox"
              data-testid="button-load-samples"
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Go to Inbox
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div>
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {toast}
        </div>
      )}

      <PageHeader
        title="Approvals"
        subtitle={
          tab === "board"
            ? `${queueCount} in approval queue · reject moves files to rejected/org/vendor/year/month`
            : "Policy rules and privilege matrix — persisted per organisation."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => load({ fresh: true })}
            disabled={loading}
            aria-label="Refresh approvals"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </Button>
        }
      />

      {error && (
        <Card className="p-3 mb-4 text-xs text-destructive border-destructive/30 bg-destructive/5">
          {error}
        </Card>
      )}

      {board.awaiting.length > 0 && (
        <Card className="p-3 mb-4 text-xs border-border bg-muted/40 flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground">
            {board.awaiting.length} document{board.awaiting.length === 1 ? "" : "s"} in the
            pipeline (parse → validate → map → journal). Click Run processing if they
            do not advance automatically.
          </p>
          <Button
            variant="outline"
            size="sm"
            disabled={processingBusy}
            onClick={() => void runProcessing()}
            data-testid="button-run-processing"
          >
            {processingBusy ? "Processing…" : "Run processing"}
          </Button>
        </Card>
      )}

      <div className="flex flex-wrap gap-1 border-b border-border mb-4">
        <button
          type="button"
          data-testid="tab-board"
          onClick={() => setTab("board")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            tab === "board"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          Board
        </button>
        <button
          type="button"
          data-testid="tab-policy"
          onClick={() => setTab("policy")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            tab === "policy"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          Policy & privileges
        </button>
      </div>

      {tab === "board" ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {COLUMNS.map((col) => {
            const cards = board[col.key];
            return (
              <Card
                key={col.key}
                className="p-3 bg-muted/30 min-h-[240px]"
                data-testid={`col-${col.key}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold">{col.label}</h3>
                  <Badge variant="outline" className="tnum text-[10px]">
                    {cards.length}
                  </Badge>
                </div>
                <div className="space-y-2">
                  {cards.map((inv) => (
                    <Card
                      key={inv.id}
                      className="p-3 cursor-pointer hover-elevate shadow-sm flex flex-col min-h-[120px]"
                      data-testid={`card-approval-${inv.id}`}
                      onClick={() => openDrawer(inv)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium truncate">{inv.vendor ?? "—"}</span>
                        <Badge variant="outline" className="tnum text-[10px] shrink-0">
                          {invId(inv.id)}
                        </Badge>
                      </div>
                      <div className="text-xs text-muted-foreground tnum mt-0.5">
                        {docNumber(inv)} · {money(inv.total, inv.currency)}
                        {col.key === "awaiting" && (
                          <span className="ml-1 capitalize">· {inv.status.replace(/_/g, " ")}</span>
                        )}
                      </div>
                      <div
                        className="flex items-center gap-1 mt-2 flex-wrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {col.key === "pending" && APPROVABLE_STATUSES.has(inv.status) && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-1.5 text-[11px]"
                            onClick={() => openDrawer(inv, true)}
                            data-testid={`edit-${inv.id}`}
                          >
                            <Pencil className="h-3 w-3 mr-0.5" />
                            Edit
                          </Button>
                        )}
                        {col.key !== "approved" && APPROVABLE_STATUSES.has(inv.status) && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-[hsl(var(--chart-1))]"
                            disabled={busyId === inv.id}
                            onClick={() => void approveInvoice(inv.id)}
                            data-testid={`approve-${inv.id}`}
                          >
                            <Check className="h-3 w-3 mr-0.5" />
                            {busyId === inv.id ? "…" : "Approve"}
                          </Button>
                        )}
                        {col.key === "pending" && inv.status === "exception" && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                            disabled={busyId === inv.id}
                            onClick={() => void rejectInvoice(inv.id)}
                            data-testid={`reject-${inv.id}`}
                          >
                            <X className="h-3 w-3 mr-0.5" />
                            Reject
                          </Button>
                        )}
                        {col.key === "approved" && inv.status === "processed" && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                            disabled={busyId === inv.id}
                            onClick={() => void rejectInvoice(inv.id)}
                            data-testid={`reject-${inv.id}`}
                          >
                            <X className="h-3 w-3 mr-0.5" />
                            Reject
                          </Button>
                        )}
                        {col.key === "approved" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-primary"
                            onClick={() => void publish(inv)}
                            data-testid={`publish-${inv.id}`}
                          >
                            <Send className="h-3 w-3 mr-0.5" />
                            Publish
                          </Button>
                        )}
                        {col.key === "rejected" && PERMANENTLY_DELETABLE.has(inv.status) && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                            disabled={busyId === inv.id}
                            onClick={() => void permanentDeleteInvoice(inv.id)}
                            data-testid={`delete-permanent-${inv.id}`}
                          >
                            <Trash2 className="h-3 w-3 mr-0.5" />
                            {busyId === inv.id ? "…" : "Delete permanently"}
                          </Button>
                        )}
                      </div>
                    </Card>
                  ))}
                  {cards.length === 0 && (
                    <p className="text-xs text-muted-foreground py-4 text-center">Empty</p>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <div className="space-y-6">
          <Card className="p-3 border-dashed text-xs text-muted-foreground">
            Policy & privileges are not connected to the backend yet. Changes here are
            local preview only and will not be saved. The Board tab uses live approval data.
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
                    {ACTIONS.map((action) => (
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
                  {ROLES.map((role) => (
                    <tr key={role} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-2.5 font-medium">{role}</td>
                      {ACTIONS.map((action) => (
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
        </div>
      )}

      <UnlockPolicyDialog
        open={unlockOpen}
        onClose={() => setUnlockOpen(false)}
        onConfirm={confirmUnlock}
      />

      <InvoiceDetailDrawer
        invoiceId={drawerInvoice?.id ?? null}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setDrawerEditMode(false);
        }}
        startInEditMode={drawerEditMode}
        onUpdated={() => load({ fresh: true })}
      />
    </div>
  );
}
