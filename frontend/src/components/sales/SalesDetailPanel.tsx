import { useState, type ReactNode } from "react";
import { Calculator, Check, ExternalLink, Truck, Receipt, FileText } from "lucide-react";
import { ApprovalPolicyNote } from "@/components/ApprovalPolicyNote";
import { DetailDrawer } from "@/components/DetailDrawer";
import { DocumentAuditTrail } from "@/components/DocumentAuditTrail";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { formatQty } from "@/lib/format";
import {
  fmtAud,
  type MatchAmountLine,
  type SalesOrder,
  type ThreeWayMatch,
} from "@/lib/v4MockData";

function MatchDocCard({
  icon: Icon,
  title,
  tone,
  children,
  onOpenDocument,
}: {
  icon: typeof Truck;
  title: string;
  tone: "muted" | "red";
  children: ReactNode;
  onOpenDocument?: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-md border p-2.5",
        tone === "red" ? "border-destructive/40 bg-destructive/5" : "border-border bg-card"
      )}
    >
      <div className="flex items-center justify-between gap-1 mb-2">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </div>
        {onOpenDocument && (
          <button
            type="button"
            onClick={onOpenDocument}
            className="text-[10px] text-primary hover:underline shrink-0"
          >
            View PDF
          </button>
        )}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function fmtQtyUom(qty: number, uom?: string | null): string {
  const q = formatQty(qty);
  return uom ? `${q} ${uom}` : q;
}

function fmtMoneyOrDash(v: number | null | undefined): string {
  if (v == null) return "—";
  return fmtAud(v);
}

function shouldShowCompared(onDoc: MatchAmountLine, forMatch: MatchAmountLine): boolean {
  const uomA = (onDoc.uom || "EA").toUpperCase();
  const uomB = (forMatch.uom || "EA").toUpperCase();
  if (uomA !== uomB) return true;
  if (Math.abs(onDoc.qty - forMatch.qty) > 0.0001) return true;
  const a = onDoc.unitPrice ?? null;
  const b = forMatch.unitPrice ?? null;
  if (a != null && b != null && Math.abs(a - b) > 0.01) return true;
  if (onDoc.unitPrice == null && forMatch.unitPrice != null) return true;
  if (onDoc.lineValue == null && forMatch.lineValue != null) return true;
  return false;
}

function MatchLegAmounts({
  onDocument,
  forMatch,
}: {
  onDocument: MatchAmountLine;
  forMatch: MatchAmountLine;
}) {
  const showCompared = shouldShowCompared(onDocument, forMatch);
  return (
    <>
      <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
        On document
      </div>
      <MatchLineRow label="Qty" value={fmtQtyUom(onDocument.qty, onDocument.uom)} />
      {onDocument.unitPrice != null && (
        <MatchLineRow label="Unit price" value={fmtMoneyOrDash(onDocument.unitPrice)} />
      )}
      {onDocument.lineValue != null && !showCompared && (
        <MatchLineRow label="Line value" value={fmtMoneyOrDash(onDocument.lineValue)} strong />
      )}
      {showCompared && (
        <>
          <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mt-2 mb-1">
            Compared
          </div>
          <MatchLineRow label="Qty" value={fmtQtyUom(forMatch.qty, forMatch.uom)} />
          {forMatch.unitPrice != null && (
            <MatchLineRow label="Unit price" value={fmtMoneyOrDash(forMatch.unitPrice)} />
          )}
          {forMatch.lineValue != null && (
            <MatchLineRow label="Line value" value={fmtMoneyOrDash(forMatch.lineValue)} strong />
          )}
        </>
      )}
    </>
  );
}

function LegacyDocAmounts({
  qty,
  unitPrice,
  value,
}: {
  qty: number | string;
  unitPrice: number;
  value: number;
}) {
  return (
    <>
      <MatchLineRow label="Qty" value={String(qty)} />
      <MatchLineRow label="Unit price" value={fmtAud(unitPrice)} />
      <MatchLineRow label="Value" value={fmtAud(value)} strong />
    </>
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

export function SalesVarianceFormulaHint() {
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
          <div className="font-mono">qty_variance = (invoice_qty − dn_qty) × invoice_unit_price</div>
          <div className="font-mono">
            price_variance = (invoice_unit_price − so_unit_price) × invoice_qty
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

function RecordDnForm({
  defaultQty,
  busy,
  onSubmit,
}: {
  defaultQty: number;
  busy: boolean;
  onSubmit: (body: {
    dn_qty: number;
    shipper?: string;
    condition_note?: string;
  }) => void | Promise<void>;
}) {
  const [qty, setQty] = useState(String(defaultQty));
  const [shipper, setShipper] = useState("");
  const [condition, setCondition] = useState("Good");

  return (
    <Card className="p-3 mt-3 border-dashed">
      <div className="text-xs font-medium mb-2">Record Delivery Note</div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div>
          <label className="text-[11px] text-muted-foreground">DN qty</label>
          <Input
            type="number"
            min={0.01}
            step="any"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className="h-8 text-sm mt-0.5"
            data-testid="input-dn-qty"
          />
        </div>
        <div>
          <label className="text-[11px] text-muted-foreground">Shipped by</label>
          <Input
            value={shipper}
            onChange={(e) => setShipper(e.target.value)}
            className="h-8 text-sm mt-0.5"
            placeholder="Name"
            data-testid="input-dn-shipper"
          />
        </div>
        <div>
          <label className="text-[11px] text-muted-foreground">Condition</label>
          <Input
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            className="h-8 text-sm mt-0.5"
            data-testid="input-dn-condition"
          />
        </div>
      </div>
      <Button
        size="sm"
        className="mt-2"
        disabled={busy || !qty || Number(qty) <= 0}
        onClick={() =>
          void onSubmit({
            dn_qty: Number(qty),
            shipper: shipper.trim() || undefined,
            condition_note: condition.trim() || undefined,
          })
        }
        data-testid="button-record-dn"
      >
        Record DN
      </Button>
    </Card>
  );
}

export function SalesDetailContent({
  so,
  match,
  invoiceId,
  busy = false,
  canApproveVariance,
  onApprove,
  onRecordDn,
  onOpenInvoice,
  onOpenSoDocument,
  onOpenDnDocument,
}: {
  so: SalesOrder;
  match: ThreeWayMatch;
  invoiceId: number | null;
  busy?: boolean;
  canApproveVariance: boolean;
  onApprove: () => void | Promise<void>;
  onRecordDn?: (body: {
    dn_qty: number;
    shipper?: string;
    condition_note?: string;
  }) => void | Promise<void>;
  onOpenInvoice?: () => void;
  onOpenSoDocument?: () => void;
  onOpenDnDocument?: () => void;
}) {
  const display = match.display;
  const varianceSubQty = "(inv_qty − dn_qty) × inv_unit_price";
  const varianceSubPrice = "(inv_unit_price − so_unit_price) × inv_qty";

  return (
    <>
      <div className="flex items-center justify-end gap-2 mb-3">
        {invoiceId != null && onOpenInvoice && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 text-xs"
            onClick={onOpenInvoice}
            data-testid="button-open-sales-invoice"
          >
            <ExternalLink className="h-3.5 w-3.5 mr-1" />
            Linked invoice
          </Button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <MatchDocCard
          icon={FileText}
          title="Sales Order"
          tone="muted"
          onOpenDocument={onOpenSoDocument}
        >
          {display ? (
            <MatchLegAmounts
              onDocument={display.poOnDocument}
              forMatch={display.poForMatch}
            />
          ) : (
            <LegacyDocAmounts qty={so.soQty} unitPrice={so.soUnitPrice} value={match.poValue} />
          )}
          <MatchLineRow label="Date" value={so.date} />
        </MatchDocCard>

        <MatchDocCard
          icon={Truck}
          title="Delivery Note"
          tone={so.dnQty === null ? "red" : "muted"}
          onOpenDocument={so.dnQty !== null ? onOpenDnDocument : undefined}
        >
          {so.dnQty === null ? (
            <div className="text-xs text-destructive py-2">
              No DN recorded. Invoice cannot be matched until delivery is recorded.
            </div>
          ) : display?.grnOnDocument && display.grnForMatch ? (
            <>
              <MatchLegAmounts
                onDocument={display.grnOnDocument}
                forMatch={display.grnForMatch}
              />
              <MatchLineRow label="Received" value={so.dnDate ?? "—"} />
              <MatchLineRow label="By" value={so.dnShipper ?? "—"} />
              <MatchLineRow label="Condition" value={so.dnCondition ?? "—"} />
            </>
          ) : (
            <>
              <MatchLineRow label="Qty" value={String(so.dnQty)} />
              <MatchLineRow label="Received" value={so.dnDate ?? "—"} />
              <MatchLineRow label="By" value={so.dnShipper ?? "—"} />
              <MatchLineRow label="Condition" value={so.dnCondition ?? "—"} />
            </>
          )}
        </MatchDocCard>

        <MatchDocCard
          icon={Receipt}
          title="Customer Invoice"
          tone="muted"
          onOpenDocument={onOpenInvoice}
        >
          <MatchLineRow label="No." value={so.invoiceNo} />
          {display?.invoiceOnDocument && display.invoiceForMatch ? (
            <MatchLegAmounts
              onDocument={display.invoiceOnDocument}
              forMatch={display.invoiceForMatch}
            />
          ) : (
            <LegacyDocAmounts
              qty={so.invoiceQty}
              unitPrice={so.invoiceUnitPrice}
              value={match.invoiceValue}
            />
          )}
        </MatchDocCard>
      </div>

      {so.dnQty === null && onRecordDn && (
        <RecordDnForm
          defaultQty={so.invoiceQty || so.soQty}
          busy={busy}
          onSubmit={onRecordDn}
        />
      )}

      <Card className="p-3 mt-3 bg-muted/30">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-2">
          Match reconciliation
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <VarianceRow
            label="Quantity variance"
            sub={varianceSubQty}
            value={match.qtyVarianceValue}
          />
          <VarianceRow
            label="Price variance"
            sub={varianceSubPrice}
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

      {so.routedForApproval && (
        <div className="mt-3">
          <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1.5">
            Variance approval
          </div>
          <ApprovalPolicyNote />
          <div className="mt-3">
            {canApproveVariance ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void onApprove()}
                data-testid="button-drawer-approve-variance"
              >
                <Check className="h-4 w-4 mr-1" /> Approve variance
              </Button>
            ) : (
              <div className="text-xs text-muted-foreground">Variance already approved.</div>
            )}
          </div>
        </div>
      )}

      {match.status === "3-Way Match" && !so.routedForApproval && (
        <div className="mt-3 text-sm text-primary flex items-center gap-1.5">
          <Check className="h-4 w-4" />
          Three-way match complete — ready for collections workflow
        </div>
      )}

      <DocumentAuditTrail docId={so.id} invoiceId={invoiceId ?? undefined} />
    </>
  );
}

export function SalesDetailSheet({
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
    <DetailDrawer
      open={open}
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size="purchase"
      testId="drawer-sales-detail"
    >
      {children}
    </DetailDrawer>
  );
}
