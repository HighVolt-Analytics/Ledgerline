import { Link } from "react-router-dom";
import { Package, Receipt, ShoppingCart } from "lucide-react";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { Badge } from "@/components/ui/badge";
import type { PurchaseDossier } from "@/api/types";
import { cn } from "@/lib/cn";
import { fmtAud, type MatchStatus } from "@/lib/v4MockData";

const ROLE_ICONS = {
  po: ShoppingCart,
  grn: Package,
  invoice: Receipt,
} as const;

function DossierMemberCard({
  member,
  onOpen,
}: {
  member: PurchaseDossier["members"][number];
  onOpen?: (invoiceId: number) => void;
}) {
  const Icon = ROLE_ICONS[member.role as keyof typeof ROLE_ICONS] ?? Receipt;

  return (
    <div
      className={cn(
        "rounded-md border p-2.5",
        member.is_current ? "border-primary/40 bg-primary/5" : "border-border bg-card",
        !member.present && "border-dashed bg-muted/20"
      )}
    >
      <div className="flex items-center justify-between gap-1 mb-2">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          <Icon className="h-3.5 w-3.5" />
          {member.label}
        </div>
        {member.present && member.invoice_id != null && member.has_stored_file && onOpen && !member.is_current && (
          <button
            type="button"
            onClick={() => onOpen(member.invoice_id!)}
            className="text-[10px] text-primary hover:underline shrink-0"
          >
            View
          </button>
        )}
      </div>
      {member.present ? (
        <div className="space-y-1">
          <div className="text-xs font-medium tnum">{member.document_ref}</div>
          {member.is_current && (
            <Badge variant="outline" className="text-[10px] h-5 px-1.5">
              Current document
            </Badge>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Not uploaded</p>
      )}
    </div>
  );
}

type InvoicePurchaseDossierSectionProps = {
  dossier: PurchaseDossier | null;
  loading: boolean;
  onOpenSibling?: (invoiceId: number) => void;
};

export function InvoicePurchaseDossierSection({
  dossier,
  loading,
  onOpenSibling,
}: InvoicePurchaseDossierSectionProps) {
  if (loading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading purchase dossier…</p>;
  }

  if (!dossier?.po_reference) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">No purchase order linked</p>
        <p className="text-xs text-muted-foreground mt-1">
          2-way match only. Upload PO / GRN documents on the Upload page with the same PO
          reference to build a dossier.
        </p>
      </div>
    );
  }

  const matchStatus = dossier.match_status as MatchStatus | null | undefined;

  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground tnum">{dossier.po_reference}</span>
        {matchStatus && <MatchStatusBadge status={matchStatus} />}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {dossier.members.map((member) => (
          <DossierMemberCard key={member.role} member={member} onOpen={onOpenSibling} />
        ))}
      </div>

      {dossier.match && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs space-y-1">
          <div className="flex justify-between gap-2">
            <span className="text-muted-foreground">PO value</span>
            <span className="tnum">{fmtAud(dossier.match.po_value)}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-muted-foreground">Invoice total</span>
            <span className="tnum">{fmtAud(dossier.match.invoice_total)}</span>
          </div>
          {dossier.match.total_deviation !== 0 && (
            <div className="flex justify-between gap-2 font-medium">
              <span className="text-muted-foreground">Deviation</span>
              <span className="tnum">{fmtAud(dossier.match.total_deviation)}</span>
            </div>
          )}
        </div>
      )}

      {dossier.purchase_order_id != null && (
        <Link to="/purchases" className="text-xs text-primary hover:underline">
          Open in Purchase Management →
        </Link>
      )}
    </div>
  );
}
