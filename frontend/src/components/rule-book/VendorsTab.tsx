import { Fragment, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  ExternalLink,
  Loader2,
  Plus,
  Settings,
  Trash2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { useToast } from "@/context/ToastContext";
import {
  useCreateVendorMaster,
  useDeleteVendorMaster,
  useDismissPendingVendor,
  usePendingVendors,
  usePromotePendingVendor,
  useUpdateVendorMaster,
  useVendorMasters,
} from "@/hooks/useMasterData";
import { cn } from "@/lib/cn";
import { fmtAud } from "@/lib/v4MockData";
import type { VendorDetectionConfig, VendorMaster } from "@/lib/v4RuleBookTypes";
import { FieldLabel } from "./FieldLabel";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { VendorDetailPanel } from "./VendorDetailPanel";
import { VendorDetectionTest } from "./VendorDetectionTest";

function maskAccount(num: string) {
  if (!num) return "—";
  return num.length <= 4 ? num : `•••• ${num.slice(-4)}`;
}

function formatBankSummary(vendor: VendorMaster, showBank: boolean) {
  if (!vendor.bank.accountNumber) {
    return <span className="text-muted-foreground">—</span>;
  }
  const bsb = vendor.bank.bsb ? `${vendor.bank.bsb} · ` : "";
  const account = showBank ? vendor.bank.accountNumber : maskAccount(vendor.bank.accountNumber);
  return (
    <span className="font-mono text-xs whitespace-nowrap">
      {bsb}
      {account}
    </span>
  );
}

function normalizeAbn(value: string): string {
  return value.replace(/\D/g, "").slice(0, 11);
}

function StatusDot({ status }: { status: string }) {
  const tone: Record<string, string> = {
    Active: "bg-[hsl(var(--chart-1))]",
    "On hold": "bg-[#9c4e2a] dark:bg-[#edc0a6]",
    "Pending registration": "bg-destructive",
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

export function VendorsTab({
  detection,
  onDetectionChange,
}: {
  detection: VendorDetectionConfig;
  onDetectionChange: (d: VendorDetectionConfig) => void;
}) {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [bankMasked, setBankMasked] = useState(true);
  const [focusBankId, setFocusBankId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, VendorMaster>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [quickName, setQuickName] = useState("");
  const [quickAbn, setQuickAbn] = useState("");
  const [linkMasterByPendingId, setLinkMasterByPendingId] = useState<Record<number, string>>({});

  const { data: vendors = [], isLoading } = useVendorMasters();
  const { data: pendingQueue = [] } = usePendingVendors();
  const createMutation = useCreateVendorMaster();
  const updateMutation = useUpdateVendorMaster();
  const deleteMutation = useDeleteVendorMaster();
  const promoteMutation = usePromotePendingVendor();
  const dismissMutation = useDismissPendingVendor();

  const weightSum =
    detection.weights.name + detection.weights.abn + detection.weights.bank + detection.weights.address;

  const registrationPending = vendors.filter((v) => v.status === "Pending registration");

  const activeVendors = useMemo(
    () => vendors.filter((vendor) => vendor.status !== "Pending registration"),
    [vendors],
  );

  const vendorById = (id: string) => vendors.find((v) => v.id === id);

  const getDraft = (vendor: VendorMaster) => drafts[vendor.id] ?? vendor;

  const patchDraft = (id: string, patch: Partial<VendorMaster>) => {
    const base = drafts[id] ?? vendorById(id);
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
      { id, patch: { ...draft, abn: normalizeAbn(draft.abn) } },
      {
        onSuccess: () => {
          clearDraft(id);
          toast({ title: "Vendor saved" });
        },
        onError: (err) =>
          toast({
            title: "Could not save vendor",
            description: err instanceof Error ? err.message : "Save failed",
            variant: "destructive",
          }),
      }
    );
  };

  const openVendor = (id: string, focusBank = false) => {
    const vendor = vendorById(id);
    if (vendor && !drafts[id]) {
      setDrafts((prev) => ({ ...prev, [id]: vendor }));
    }
    setExpandedId(id);
    setFocusBankId(focusBank ? id : null);
  };

  const closeVendor = (id: string) => {
    if (dirtyIds.has(id)) {
      const keep = window.confirm("Discard unsaved vendor changes?");
      if (!keep) return;
    }
    clearDraft(id);
    setExpandedId(null);
    setFocusBankId(null);
  };

  const quickAddVendor = () => {
    const name = quickName.trim();
    if (!name) {
      toast({ title: "Enter a vendor name", variant: "destructive" });
      return;
    }
    createMutation.mutate(
      {
        name,
        aliases: [],
        abn: normalizeAbn(quickAbn),
        billingAddress: { street: "", suburb: "", postcode: "", country: "" },
        bank: { accountNumber: "", accountName: "", bankName: "" },
        defaultLedger: "Marketing Expense",
        status: "Active",
      },
      {
        onSuccess: (created) => {
          setQuickName("");
          setQuickAbn("");
          openVendor(created.id);
          toast({
            title: "Vendor created",
            description: "Add bank details if needed, then click Save vendor.",
          });
        },
        onError: (err) =>
          toast({
            title: "Could not create vendor",
            description: err instanceof Error ? err.message : "Create failed",
            variant: "destructive",
          }),
      }
    );
  };

  const addVendor = () => {
    setQuickName("New vendor");
    setQuickAbn("");
  };

  const completePendingRegistration = (
    pendingId: number,
    name: string,
    masterId?: string,
  ) => {
    promoteMutation.mutate(
      {
        pendingId,
        body: masterId
          ? { masterId, name }
          : { name, status: "Pending registration" },
      },
      {
        onSuccess: (vendor) => {
          openVendor(vendor.id, true);
          setLinkMasterByPendingId((prev) => {
            const next = { ...prev };
            delete next[pendingId];
            return next;
          });
          toast({
            title: masterId ? "Linked to existing vendor" : "Vendor created",
            description: masterId
              ? `${vendor.name} is now registered for held invoices.`
              : "Complete bank and ledger details.",
          });
        },
        onError: (err) =>
          toast({
            title: "Could not register vendor",
            description: err instanceof Error ? err.message : "Registration failed",
            variant: "destructive",
          }),
      }
    );
  };

  const removeVendor = (vendor: VendorMaster) => {
    if (
      !window.confirm(
        `Remove vendor "${vendor.name}" from the rule book? This cannot be undone.`
      )
    ) {
      return;
    }
    deleteMutation.mutate(vendor.id, {
      onSuccess: () => {
        clearDraft(vendor.id);
        if (expandedId === vendor.id) setExpandedId(null);
        toast({ title: "Vendor removed" });
      },
      onError: (err) =>
        toast({
          title: "Could not remove vendor",
          description: err instanceof Error ? err.message : "Delete failed",
          variant: "destructive",
        }),
    });
  };

  const dismissPending = (pendingId: number, name: string) => {
    dismissMutation.mutate(pendingId, {
      onSuccess: () => toast({ title: "Removed from queue", description: name }),
      onError: (err) =>
        toast({
          title: "Could not dismiss",
          description: err instanceof Error ? err.message : "Dismiss failed",
          variant: "destructive",
        }),
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading vendor masters…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-3 text-sm text-muted-foreground">
        <strong>Vendor masters</strong> drive detection, VR12 registration holds, and GL defaults.
        For email routing and payout methods, use the standalone{" "}
        <strong>Vendors</strong> page (capture registry).
      </Card>
      <p className="text-sm text-muted-foreground max-w-2xl">
        Auto-detect known vendors from inbound documents using four weighted signals. Unknown vendors
        are flagged for registration. Bank details power the Payments module.
      </p>

      <Card className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <Settings className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Detection configuration</h3>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {(["name", "abn", "bank", "address"] as const).map((key) => (
            <div key={key}>
              <div className="flex items-center justify-between text-xs mb-1.5">
                <span className="font-medium capitalize">{key} weight</span>
                <span className="tnum text-muted-foreground">{detection.weights[key]}</span>
              </div>
              <Slider
                value={detection.weights[key]}
                min={0}
                max={100}
                step={5}
                onValueChange={(next) =>
                  onDetectionChange({
                    ...detection,
                    weights: { ...detection.weights, [key]: next },
                  })
                }
                data-testid={`weight-${key}`}
              />
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-4 mt-4 pt-3 border-t border-border">
          <div className="flex-1 min-w-[200px]">
            <div className="flex items-center justify-between text-xs mb-1.5">
              <span className="font-medium">Auto-match threshold</span>
              <span className="tnum text-muted-foreground">{detection.threshold}%</span>
            </div>
            <Slider
              value={detection.threshold}
              min={0}
              max={100}
              step={5}
              onValueChange={(next) =>
                onDetectionChange({ ...detection, threshold: next })
              }
              data-testid="threshold-slider"
            />
          </div>
          <div className="text-xs">
            <span className="text-muted-foreground">Weights sum: </span>
            <span
              className={cn(
                "tnum font-semibold",
                weightSum === 100 ? "text-[hsl(var(--chart-1))]" : "text-destructive"
              )}
            >
              {weightSum}
            </span>
            {weightSum !== 100 && (
              <span className="text-destructive ml-1">(must equal 100)</span>
            )}
          </div>
          <Button
            size="sm"
            data-testid="save-detection-config"
            onClick={() =>
              toast({
                title: "Detection config saved",
                description:
                  weightSum === 100
                    ? "Weights and threshold updated."
                    : "Warning: weights do not sum to 100.",
              })
            }
          >
            Save
          </Button>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="flex items-center justify-between gap-2 p-3 border-b border-border flex-wrap">
          <h3 className="text-sm font-semibold">Vendor master ({vendors.length})</h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setBankMasked((m) => !m)}
              className="text-xs text-muted-foreground hover:text-foreground"
              data-testid="toggle-bank-mask"
            >
              {bankMasked ? "Show bank details" : "Hide bank details"}
            </button>
            <Button
              size="sm"
              variant="outline"
              onClick={addVendor}
              disabled={createMutation.isPending}
              data-testid="button-new-vendor"
            >
              <Plus className="h-4 w-4 mr-1" /> New Vendor
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2 p-3 border-b border-border bg-muted/10">
          <div className="min-w-[200px] flex-1">
            <FieldLabel label="Quick add — name">
              <Input
                value={quickName}
                onChange={(e) => setQuickName(e.target.value)}
                placeholder="Sysco Foods Australia Pty Ltd"
                className="h-8 text-sm"
                data-testid="quick-vendor-name"
              />
            </FieldLabel>
          </div>
          <div className="min-w-[160px]">
            <FieldLabel label="ABN">
              <Input
                value={quickAbn}
                onChange={(e) => setQuickAbn(e.target.value)}
                placeholder="51824753556"
                className="h-8 text-xs font-mono"
                data-testid="quick-vendor-abn"
              />
            </FieldLabel>
          </div>
          <Button
            size="sm"
            onClick={quickAddVendor}
            disabled={createMutation.isPending || !quickName.trim()}
            data-testid="button-quick-add-vendor"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Plus className="h-4 w-4 mr-1" /> Add vendor
              </>
            )}
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border text-left">
                <th className="px-3 py-2 font-medium">Vendor</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Bank</th>
                <th className="px-3 py-2 font-medium">Default ledger</th>
                <th className="px-3 py-2 font-medium text-right">YTD spend</th>
                <th className="px-3 py-2 font-medium text-right">Inv</th>
                <th className="px-3 py-2 font-medium">Last match</th>
              </tr>
            </thead>
            <tbody>
              {vendors.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No vendors yet. Click <span className="font-medium text-foreground">New Vendor</span>{" "}
                    to register one before sending invoices, or complete registration from the queue
                    below when a document is held.
                  </td>
                </tr>
              )}
              {vendors.map((v) => {
                const open = expandedId === v.id;
                const draft = getDraft(v);
                const dirty = dirtyIds.has(v.id);
                return (
                  <Fragment key={v.id}>
                    <tr
                      className="row-band border-b border-border/60 cursor-pointer hover:bg-muted/40"
                      onClick={() => {
                        if (open) closeVendor(v.id);
                        else openVendor(v.id);
                      }}
                      data-testid={`vendor-row-${v.id}`}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          {open ? (
                            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          )}
                          <span className="font-medium">
                            {dirty ? draft.name : v.name}
                            {dirty && (
                              <span className="ml-2 text-[10px] ds-warning-text">
                                unsaved
                              </span>
                            )}
                          </span>
                        </div>
                        <span className="text-[11px] text-muted-foreground font-mono ml-5">
                          ABN {v.abn}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={v.status} />
                      </td>
                      <td className="px-3 py-2">{formatBankSummary(v, !bankMasked)}</td>
                      <td className="px-3 py-2">
                        {v.defaultLedger === "—" ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <AccountBadge account={v.defaultLedger} />
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tnum">{fmtAud(v.totalSpendYTD)}</td>
                      <td className="px-3 py-2 text-right tnum">{v.invoiceCount}</td>
                      <td className="px-3 py-2">
                        <ConfidenceBar value={v.matchConfidence ?? 0} />
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={7} className="p-0 border-b border-border">
                          <VendorDetailPanel
                            vendor={draft}
                            onChange={(patch) => patchDraft(v.id, patch)}
                            masked={bankMasked}
                            onToggleMask={() => setBankMasked((m) => !m)}
                            focusBank={focusBankId === v.id}
                          />
                          <div className="flex items-center justify-between gap-2 px-4 pb-4 bg-muted/20">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                              disabled={deleteMutation.isPending}
                              onClick={(e) => {
                                e.stopPropagation();
                                removeVendor(v);
                              }}
                              data-testid={`delete-vendor-${v.id}`}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-1" />
                              Remove vendor
                            </Button>
                            <div className="flex items-center gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  closeVendor(v.id);
                                }}
                              >
                                Cancel
                              </Button>
                              <Button
                                size="sm"
                                disabled={!dirty || updateMutation.isPending}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  saveDraft(v.id);
                                }}
                                data-testid={`save-vendor-${v.id}`}
                              >
                                {updateMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  "Save vendor"
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

      <Card
        className="p-4 border-destructive/30 bg-destructive/5"
        data-testid="pending-vendor-queue"
      >
        <div className="flex items-center gap-2 mb-3">
          <AlertCircle className="h-4 w-4 text-destructive" />
          <h3 className="text-sm font-semibold">Pending vendor registration queue</h3>
        </div>
        {pendingQueue.length === 0 && registrationPending.length === 0 ? (
          <p className="text-xs text-muted-foreground">No vendors pending registration.</p>
        ) : (
          <div className="space-y-2">
            {pendingQueue.map((item) => (
              <div
                key={`pending-${item.id}`}
                className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-border bg-background p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">{item.detectedName}</div>
                  <div className="text-xs text-muted-foreground">
                    Detected on invoice · match confidence {item.confidence}% (below threshold)
                    {item.detectedAbn ? ` · ABN ${item.detectedAbn}` : ""}
                    {item.sourceInvoiceId ? (
                      <>
                        {" · "}
                        <Link
                          to={`/upload?doc=${item.sourceInvoiceId}`}
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          View source invoice
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                      </>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  {activeVendors.length > 0 ? (
                    <Select
                      value={linkMasterByPendingId[item.id] ?? ""}
                      onValueChange={(value) =>
                        setLinkMasterByPendingId((prev) => ({ ...prev, [item.id]: value }))
                      }
                      options={activeVendors.map((vendor) => ({
                        value: vendor.id,
                        label: vendor.name,
                      }))}
                      placeholder="Link to existing…"
                      size="sm"
                      className="w-[200px] h-8 text-xs"
                    />
                  ) : null}
                  {linkMasterByPendingId[item.id] ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={promoteMutation.isPending}
                      onClick={() =>
                        completePendingRegistration(
                          item.id,
                          item.detectedName,
                          linkMasterByPendingId[item.id],
                        )
                      }
                      data-testid={`link-existing-pending-vendor-${item.id}`}
                    >
                      Link to master
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    disabled={promoteMutation.isPending}
                    onClick={() => completePendingRegistration(item.id, item.detectedName)}
                    data-testid={`complete-registration-pending-${item.id}`}
                  >
                    <ClipboardCheck className="h-4 w-4 mr-1" />
                    Complete Registration
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={dismissMutation.isPending}
                    onClick={() => dismissPending(item.id, item.detectedName)}
                    data-testid={`dismiss-pending-${item.id}`}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Dismiss
                  </Button>
                </div>
              </div>
            ))}
            {registrationPending.map((v) => (
              <div
                key={v.id}
                className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-border bg-background p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">{v.name}</div>
                  <div className="text-xs text-muted-foreground">
                    Registration in progress · match confidence {v.matchConfidence}% · complete bank
                    details
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={() => openVendor(v.id, true)}
                  data-testid={`complete-registration-${v.id}`}
                >
                  <ClipboardCheck className="h-4 w-4 mr-1" />
                  Complete Registration
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={deleteMutation.isPending}
                  onClick={() => removeVendor(v)}
                  data-testid={`remove-registration-vendor-${v.id}`}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  Remove
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <VendorDetectionTest vendors={vendors} config={detection} />
    </div>
  );
}
