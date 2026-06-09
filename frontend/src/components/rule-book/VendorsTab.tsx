import { Fragment, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Loader2,
  Settings,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { useToast } from "@/context/ToastContext";
import {
  usePendingVendors,
  usePromotePendingVendor,
  useUpdateVendorMaster,
  useVendorMasters,
} from "@/hooks/useMasterData";
import { cn } from "@/lib/cn";
import { fmtAud } from "@/lib/v4MockData";
import type { VendorDetectionConfig, VendorMaster } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { VendorDetailPanel } from "./VendorDetailPanel";
import { VendorDetectionTest } from "./VendorDetectionTest";

const SAVE_DEBOUNCE_MS = 600;

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

function StatusDot({ status }: { status: string }) {
  const tone: Record<string, string> = {
    Active: "bg-[hsl(var(--chart-1))]",
    "On hold": "bg-[hsl(43_74%_49%)]",
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
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const { data: vendors = [], isLoading } = useVendorMasters();
  const { data: pendingQueue = [] } = usePendingVendors();
  const updateMutation = useUpdateVendorMaster();
  const promoteMutation = usePromotePendingVendor();

  const weightSum =
    detection.weights.name + detection.weights.abn + detection.weights.bank + detection.weights.address;

  const registrationPending = vendors.filter((v) => v.status === "Pending registration");

  useEffect(() => {
    const timers = saveTimers.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const updateVendor = (id: string, patch: Partial<VendorMaster>) => {
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
                title: "Could not save vendor",
                description: err instanceof Error ? err.message : "Save failed",
                variant: "destructive",
              }),
          }
        );
        saveTimers.current.delete(id);
      }, SAVE_DEBOUNCE_MS)
    );
  };

  const openVendor = (id: string, focusBank = false) => {
    setExpandedId(id);
    setFocusBankId(focusBank ? id : null);
  };

  const completePendingRegistration = (pendingId: number, name: string) => {
    promoteMutation.mutate(
      { pendingId, body: { name, status: "Pending registration" } },
      {
        onSuccess: (vendor) => {
          openVendor(vendor.id, true);
          toast({ title: "Vendor created", description: "Complete bank and ledger details." });
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
        <div className="flex items-center justify-between gap-2 p-3 border-b border-border">
          <h3 className="text-sm font-semibold">Vendor master ({vendors.length})</h3>
          <button
            type="button"
            onClick={() => setBankMasked((m) => !m)}
            className="text-xs text-muted-foreground hover:text-foreground"
            data-testid="toggle-bank-mask"
          >
            {bankMasked ? "Show bank details" : "Hide bank details"}
          </button>
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
              {vendors.map((v) => {
                const open = expandedId === v.id;
                return (
                  <Fragment key={v.id}>
                    <tr
                      className="row-band border-b border-border/60 cursor-pointer hover:bg-muted/40"
                      onClick={() => {
                        if (open) {
                          setExpandedId(null);
                          setFocusBankId(null);
                        } else {
                          openVendor(v.id);
                        }
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
                          <span className="font-medium">{v.name}</span>
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
                            vendor={v}
                            onChange={(patch) => updateVendor(v.id, patch)}
                            masked={bankMasked}
                            onToggleMask={() => setBankMasked((m) => !m)}
                            focusBank={focusBankId === v.id}
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
                  </div>
                </div>
                <Button
                  size="sm"
                  disabled={promoteMutation.isPending}
                  onClick={() => completePendingRegistration(item.id, item.detectedName)}
                  data-testid={`complete-registration-pending-${item.id}`}
                >
                  <ClipboardCheck className="h-4 w-4 mr-1" />
                  Complete Registration
                </Button>
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
              </div>
            ))}
          </div>
        )}
      </Card>

      <VendorDetectionTest vendors={vendors} config={detection} />
    </div>
  );
}
