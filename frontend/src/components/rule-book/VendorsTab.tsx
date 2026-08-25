import { Fragment, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  ExternalLink,
  Loader2,
  Mail,
  Plus,
  Settings,
  Trash2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { useToast } from "@/context/ToastContext";
import { CreationsVendorsTabSkeleton } from "@/components/skeleton/PageSkeletons";
import {
  useCreateVendorMaster,
  useDeleteVendorMaster,
  useDismissPendingVendor,
  usePendingVendors,
  usePromotePendingVendor,
  useSendVendorMasterConfirmation,
  useUpdateVendorMaster,
  useVendorMasters,
} from "@/hooks/useMasterData";
import { cn } from "@/lib/cn";
import { fmtAud } from "@/lib/v4MockData";
import { BUSINESS_REGISTRATION_NUMBER_LABEL, normalizeCurrencyCode } from "@/lib/format";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import type { PendingVendorRecord } from "@/lib/masterDataApi";
import type { VendorDetectionConfig, VendorMaster } from "@/lib/v4RuleBookTypes";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { VendorDetailPanel } from "./VendorDetailPanel";
import { VendorDetectionTest } from "./VendorDetectionTest";
import {
  VendorRegistrationDialog,
  vendorDraftFromPending,
} from "./VendorRegistrationDialog";

const VENDOR_SECTIONS = [
  { value: "pending", label: "Pending", testid: "tab-vendors-pending" },
  { value: "list", label: "Vendor list", testid: "tab-vendors-list" },
] as const;

type VendorSection = (typeof VENDOR_SECTIONS)[number]["value"];

type VendorRegistrationState =
  | { kind: "pending"; pendingId: number; draft: VendorMaster; sourceInvoiceId?: number }
  | { kind: "vendor"; vendorId: string; draft: VendorMaster };

function maskAccount(num: string) {
  if (!num) return "—";
  return num.length <= 4 ? num : `•••• ${num.slice(-4)}`;
}

function formatAccountNumber(vendor: VendorMaster, showBank: boolean) {
  if (!vendor.bank.accountNumber) {
    return <span className="text-muted-foreground">—</span>;
  }
  const account = showBank ? vendor.bank.accountNumber : maskAccount(vendor.bank.accountNumber);
  return <span className="font-mono text-xs whitespace-nowrap">{account}</span>;
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
  initialSearchQuery,
}: {
  detection: VendorDetectionConfig;
  onDetectionChange: (d: VendorDetectionConfig) => void;
  initialSearchQuery?: string | null;
}) {
  const { toast } = useToast();
  const { data: institution } = useInstitutionSettings();
  const booksCurrency = normalizeCurrencyCode(institution?.currency) ?? "";
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pinToTopId, setPinToTopId] = useState<string | null>(null);
  const [bankMasked, setBankMasked] = useState(true);
  const [focusBankId, setFocusBankId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, VendorMaster>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [linkMasterByPendingId, setLinkMasterByPendingId] = useState<Record<number, string>>({});
  const [section, setSection] = useState<VendorSection>("pending");
  const [registration, setRegistration] = useState<VendorRegistrationState | null>(null);

  const { data: vendors = [], isLoading } = useVendorMasters();
  const { data: pendingQueue = [] } = usePendingVendors();
  const createMutation = useCreateVendorMaster();
  const updateMutation = useUpdateVendorMaster();
  const deleteMutation = useDeleteVendorMaster();
  const promoteMutation = usePromotePendingVendor();
  const dismissMutation = useDismissPendingVendor();
  const sendConfirmationMutation = useSendVendorMasterConfirmation();

  const sendVendorConfirmation = (vendor: VendorMaster) => {
    sendConfirmationMutation.mutate(vendor.id, {
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

  const weightSum =
    detection.weights.name + detection.weights.abn + detection.weights.bank + detection.weights.address;

  const registrationPending = vendors.filter((v) => v.status === "Pending registration");

  const activeVendors = useMemo(
    () => vendors.filter((vendor) => vendor.status !== "Pending registration"),
    [vendors],
  );

  const listSearch = initialSearchQuery?.trim().toLowerCase() ?? "";

  const visibleVendors = useMemo(() => {
    const matchesSearch = (vendor: VendorMaster) => {
      if (!listSearch) return true;
      const haystack = [vendor.name, vendor.abn, vendor.contactPhone, ...vendor.aliases]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(listSearch);
    };

    const rows = activeVendors.filter((vendor) => vendor.id === pinToTopId || matchesSearch(vendor));
    if (!pinToTopId) return rows;
    const idx = rows.findIndex((vendor) => vendor.id === pinToTopId);
    if (idx > 0) return [rows[idx]!, ...rows.slice(0, idx), ...rows.slice(idx + 1)];
    if (idx === 0) return rows;
    const pinned = vendors.find((vendor) => vendor.id === pinToTopId);
    return pinned ? [pinned, ...rows] : rows;
  }, [activeVendors, listSearch, pinToTopId, vendors]);

  useEffect(() => {
    if (!listSearch || visibleVendors.length === 0) return;
    setExpandedId(visibleVendors[0]!.id);
  }, [listSearch, visibleVendors]);

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
    if (pinToTopId === id) setPinToTopId(null);
  };

  const addVendor = () => {
    createMutation.mutate(
      {
        name: "New vendor",
        aliases: [],
        abn: "",
        billingAddress: { street: "", suburb: "", postcode: "", country: "" },
        bank: { accountNumber: "", accountName: "", bankName: "" },
        defaultLedger: "Marketing Expense",
        status: "Active",
      },
      {
        onSuccess: (created) => {
          setSection("list");
          setPinToTopId(created.id);
          setDrafts((prev) => ({ ...prev, [created.id]: created }));
          setExpandedId(created.id);
          toast({
            title: "Vendor created",
            description: "Edit details, then click Save vendor.",
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
          setSection("list");
          setPinToTopId(vendor.id);
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

  const openPendingRegistration = (item: PendingVendorRecord) => {
    setRegistration({
      kind: "pending",
      pendingId: item.id,
      draft: vendorDraftFromPending(item),
      sourceInvoiceId: item.sourceInvoiceId,
    });
  };

  const openVendorRegistration = (vendor: VendorMaster) => {
    const draft = getDraft(vendor);
    setRegistration({
      kind: "vendor",
      vendorId: vendor.id,
      draft:
        draft.status === "Pending registration"
          ? { ...draft, status: "Active" }
          : draft,
    });
  };

  const saveRegistration = (draft: VendorMaster) => {
    const name = draft.name.trim();
    if (!name) {
      toast({
        title: "Vendor name is required",
        variant: "destructive",
      });
      return;
    }
    if (!registration) return;
    const patch = { ...draft, name, abn: normalizeAbn(draft.abn) };

    if (registration.kind === "pending") {
      createMutation.mutate(
        { ...patch, id: "" },
        {
          onSuccess: (created) => {
            promoteMutation.mutate(
              {
                pendingId: registration.pendingId,
                body: { masterId: created.id, name: created.name },
              },
              {
                onSuccess: () => {
                  setRegistration(null);
                  setLinkMasterByPendingId((prev) => {
                    const next = { ...prev };
                    delete next[registration.pendingId];
                    return next;
                  });
                  toast({
                    title: "Vendor registered",
                    description: created.name,
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
          },
          onError: (err) =>
            toast({
              title: "Could not create vendor",
              description: err instanceof Error ? err.message : "Create failed",
              variant: "destructive",
            }),
        }
      );
      return;
    }

    updateMutation.mutate(
      { id: registration.vendorId, patch },
      {
        onSuccess: () => {
          clearDraft(registration.vendorId);
          setRegistration(null);
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
        if (pinToTopId === vendor.id) setPinToTopId(null);
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
    return <CreationsVendorsTabSkeleton />;
  }

  return (
    <div className="space-y-4">
      <PageTabs
        value={section}
        onChange={(value) => setSection(value as VendorSection)}
        data-testid="vendors-section-tabs"
        tabs={VENDOR_SECTIONS.map((row) => ({
          value: row.value,
          label: row.label,
          testid: row.testid,
          secondary: true,
        }))}
      />

      <PageTabPanel value="list" active={section} className="mt-0">
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
              onClick={addVendor}
              disabled={createMutation.isPending}
              data-testid="button-add-vendor"
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
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border text-left">
                <th className="px-3 py-2 font-medium">Vendor</th>
                <th className="px-3 py-2 font-medium">Phone</th>
                <th className="px-3 py-2 font-medium">Bank account number</th>
                <th className="px-3 py-2 font-medium">Default ledger</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium text-right">YTD spend</th>
                <th className="px-3 py-2 font-medium text-right">Inv</th>
                <th className="px-3 py-2 font-medium text-left">Last match</th>
              </tr>
            </thead>
            <tbody>
              {visibleVendors.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    {listSearch
                      ? `No vendors match “${initialSearchQuery?.trim()}”.`
                      : (
                        <>
                          No vendors yet. Click <span className="font-medium text-foreground">Add vendor</span>{" "}
                          to register one before sending invoices, or complete registration from Pending
                          when a document is held.
                        </>
                      )}
                  </td>
                </tr>
              )}
              {visibleVendors.map((v) => {
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
                          {BUSINESS_REGISTRATION_NUMBER_LABEL} {v.abn}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                        {(dirty ? draft.contactPhone : v.contactPhone) || (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2">{formatAccountNumber(dirty ? draft : v, !bankMasked)}</td>
                      <td className="px-3 py-2">
                        {v.defaultLedger === "—" ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <AccountBadge account={v.defaultLedger} />
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={dirty ? draft.status : v.status} />
                      </td>
                      <td className="px-3 py-2 text-right tnum">{fmtAud(v.totalSpendYTD, booksCurrency)}</td>
                      <td className="px-3 py-2 text-right tnum">{v.invoiceCount}</td>
                      <td className="px-3 py-2 text-left">
                        <ConfidenceBar value={v.matchConfidence ?? 0} />
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={8} className="p-0 border-b border-border">
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
                                disabled={sendConfirmationMutation.isPending}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  sendVendorConfirmation(dirty ? draft : v);
                                }}
                                data-testid={`send-vendor-confirmation-${v.id}`}
                              >
                                {sendConfirmationMutation.isPending ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <>
                                    <Mail className="h-3.5 w-3.5 mr-1" />
                                    {v.confirmationSentAt ? "Resend confirmation" : "Send confirmation"}
                                  </>
                                )}
                              </Button>
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
      </PageTabPanel>

      <PageTabPanel value="pending" active={section} className="mt-0 space-y-4">
      <Card
        className="p-4 border-destructive/30 bg-destructive/5"
        data-testid="pending-vendor-queue"
      >
        <div className="flex items-center gap-2 mb-3">
          <AlertCircle className="h-4 w-4 text-destructive" />
          <h3 className="text-sm font-semibold">Pending registration queue</h3>
        </div>
        {pendingQueue.length === 0 && registrationPending.length === 0 ? (
          <p className="text-xs text-muted-foreground">No vendors pending registration.</p>
        ) : (
          <div className="space-y-2">
            {pendingQueue.map((item) => (
              <div
                key={`pending-${item.id}`}
                className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-border bg-transparent p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{item.detectedName}</div>
                  <div className="text-xs text-muted-foreground">
                    Detected on invoice · match confidence {item.confidence}% (below threshold)
                    {item.detectedAbn ? ` · ${BUSINESS_REGISTRATION_NUMBER_LABEL} ${item.detectedAbn}` : ""}
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
                <div className="flex items-center gap-2 flex-wrap shrink-0 ml-auto">
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
                      variant="outline"
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
                    disabled={promoteMutation.isPending || createMutation.isPending}
                    onClick={() => openPendingRegistration(item)}
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
                className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-border bg-transparent p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{v.name}</div>
                  <div className="text-xs text-muted-foreground">
                    Registration in progress · match confidence {v.matchConfidence}% · complete bank
                    details
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap shrink-0 ml-auto">
                  {/* Keep Complete Registration aligned with pending rows that show "Link to existing…" */}
                  {activeVendors.length > 0 ? (
                    <div className="hidden sm:block w-[200px] shrink-0" aria-hidden />
                  ) : null}
                  <Button
                    size="sm"
                    onClick={() => openVendorRegistration(v)}
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
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <Settings className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Detection configuration</h3>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {(["name", "abn", "bank", "address"] as const).map((key) => (
            <div key={key}>
              <div className="flex items-center justify-between text-xs mb-1.5">
                <span className={key === "abn" ? "font-medium" : "font-medium capitalize"}>
                  {key === "abn" ? BUSINESS_REGISTRATION_NUMBER_LABEL : key} weight
                </span>
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

      <VendorDetectionTest vendors={vendors} config={detection} />
      </PageTabPanel>

      <VendorRegistrationDialog
        open={registration != null}
        initialVendor={registration?.draft ?? null}
        sourceInvoiceId={registration?.kind === "pending" ? registration.sourceInvoiceId : undefined}
        onClose={() => setRegistration(null)}
        onSave={saveRegistration}
        saving={
          createMutation.isPending || promoteMutation.isPending || updateMutation.isPending
        }
      />
    </div>
  );
}
