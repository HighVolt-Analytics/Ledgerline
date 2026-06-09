import { useState, type ReactNode } from "react";
import { Calculator, Check, ChevronRight, Package, Receipt, ShoppingCart } from "lucide-react";
import { ApprovalPolicyNote } from "@/components/ApprovalPolicyNote";
import { ApproverChip } from "@/components/ApproverChip";
import { DetailDrawer } from "@/components/DetailDrawer";
import { DocumentAuditTrail } from "@/components/DocumentAuditTrail";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  fmtAud,
  SANDBOX_CURRENT_USER,
  type PurchaseOrder,
  type ThreeWayMatch,
} from "@/lib/v4MockData";
function MatchDocCard({
  icon: Icon,
  title,
  tone,
  children,
}: {
  icon: typeof Package;
  title: string;
  tone: "muted" | "red";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-md border p-2.5",
        tone === "red" ? "border-destructive/40 bg-destructive/5" : "border-border bg-card"
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function MatchLineRow({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tnum text-right", strong && "font-semibold")}>{value}</span>
    </div>
  );
}

function VarianceRow({ label, sub, value }: { label: string; sub: string; value: number }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm">{label}</span>
        <span
          className={cn(
            "tnum text-sm font-medium",
            value !== 0 && "text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]"
          )}
        >
          {fmtAud(value)}
        </span>
      </div>
      <div className="font-mono text-[10px] text-muted-foreground">{sub}</div>
    </div>
  );
}

export function VarianceFormulaHint() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        data-testid="button-formula"
        onClick={() => setOpen((o) => !o)}
      >
        <Calculator className="h-3.5 w-3.5" /> Variance formula
      </button>
      {open && (
        <Card className="absolute right-0 z-10 mt-1 p-3 max-w-xs text-xs space-y-1.5 shadow-md">
          <div className="font-medium">Three-way match formula</div>
          <div className="font-mono">qty_variance = (invoice_qty − grn_qty) × invoice_unit_price</div>
          <div className="font-mono">
            price_variance = (invoice_unit_price − po_unit_price) × invoice_qty
          </div>
          <div className="font-mono">total_deviation = qty_variance + price_variance</div>
          <div className="text-muted-foreground pt-1">
            A non-zero total deviation routes the document for tiered approval.
          </div>
        </Card>
      )}
    </div>
  );
}

export function PurchaseDetailContent({
  po,
  match,
  onApprove,
}: {
  po: PurchaseOrder;
  match: ThreeWayMatch;
  onApprove: () => void;
}) {
  const pending = po.approvers?.find((a) => a.state === "pending");
  const canApprove = Boolean(pending && pending.id === SANDBOX_CURRENT_USER.id);

  return (
    <>
      <div className="grid grid-cols-3 gap-2">
        <MatchDocCard icon={ShoppingCart} title="Purchase Order" tone="muted">
          <MatchLineRow label="Qty" value={String(po.poQty)} />
          <MatchLineRow label="Unit price" value={fmtAud(po.poUnitPrice)} />
          <MatchLineRow label="Value" value={fmtAud(match.poValue)} strong />
          <MatchLineRow label="Date" value={po.date} />
        </MatchDocCard>

        <MatchDocCard icon={Package} title="Goods Receipt" tone={po.grnQty === null ? "red" : "muted"}>
          {po.grnQty === null ? (
            <div className="text-xs text-destructive py-2">
              No GRN received. Invoice cannot be matched until goods are receipted.
            </div>
          ) : (
            <>
              <MatchLineRow label="Qty" value={String(po.grnQty)} />
              <MatchLineRow label="Received" value={po.grnDate ?? "—"} />
              <MatchLineRow label="By" value={po.grnReceiver ?? "—"} />
              <MatchLineRow label="Condition" value={po.grnCondition ?? "—"} />
            </>
          )}
        </MatchDocCard>

        <MatchDocCard icon={Receipt} title="Supplier Invoice" tone="muted">
          <MatchLineRow label="No." value={po.invoiceNo} />
          <MatchLineRow label="Qty" value={String(po.invoiceQty)} />
          <MatchLineRow label="Unit price" value={fmtAud(po.invoiceUnitPrice)} />
          <MatchLineRow label="Value" value={fmtAud(match.invoiceValue)} strong />
        </MatchDocCard>
      </div>

      <Card className="p-3 mt-3 bg-muted/30">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">
          Match reconciliation
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <VarianceRow
            label="Quantity variance"
            sub="(inv_qty − grn_qty) × inv_unit_price"
            value={match.qtyVarianceValue}
          />
          <VarianceRow
            label="Price variance"
            sub="(inv_unit_price − po_unit_price) × inv_qty"
            value={match.priceVarianceValue}
          />
        </div>
        <div className="border-t border-border/60 mt-2 pt-2 flex items-center justify-between text-sm">
          <span className="font-medium">Total deviation</span>
          <span
            className={cn(
              "tnum font-semibold",
              match.totalDeviation !== 0
                ? "text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]"
                : "text-primary"
            )}
          >
            {fmtAud(match.totalDeviation)}
          </span>
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground mt-1.5">
          <span>
            Invoice subtotal {fmtAud(match.invoiceValue)} + GST {fmtAud(match.invoiceGst)}
          </span>
          <span className="tnum">Invoice total {fmtAud(match.invoiceTotal)}</span>
        </div>
      </Card>

      {po.routedForApproval && po.approvers && (
        <div className="mt-3">
          <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
            Approval chain
          </div>
          <div className="flex flex-wrap gap-1.5">
            {po.approvers.map((a) => (
              <ApproverChip key={a.id} {...a} />
            ))}
          </div>
          <div className="mt-1.5">
            <ApprovalPolicyNote />
          </div>
          <div className="mt-3">
            {canApprove ? (
              <Button size="sm" onClick={onApprove} data-testid="button-drawer-approve-variance">
                <Check className="h-4 w-4 mr-1" /> Approve variance ({pending?.role})
              </Button>
            ) : pending ? (
              <Button size="sm" disabled>
                Awaiting {pending.name}
              </Button>
            ) : (
              <div className="inline-flex items-center gap-1.5 text-sm text-primary">
                <Check className="h-4 w-4" />
                Variance fully approved — ready to progress to payment
                <ChevronRight className="h-3.5 w-3.5" />
              </div>
            )}
          </div>
        </div>
      )}

      <DocumentAuditTrail docId={po.id} />
    </>
  );
}

export function PurchaseDetailSheet({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <DetailDrawer open={open} onClose={onClose} title={title} subtitle={subtitle} size="lg">
      {children}
    </DetailDrawer>
  );
}
