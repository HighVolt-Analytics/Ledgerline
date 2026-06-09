import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Upload } from "lucide-react";
import { api } from "@/api/client";
import type { InvoiceDetails } from "@/api/types";
import { InvoiceDocumentViewer } from "@/components/InvoiceFilePreview";
import { PageHeader } from "@/components/PageHeader";
import { invoiceStage, StageBadge } from "@/components/StageBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { invId, money } from "@/lib/format";

export function InvoiceDetailPage() {
  const { id } = useParams();
  const [inv, setInv] = useState<InvoiceDetails | null>(null);

  const load = useCallback(() => {
    if (id) api.getInvoice(Number(id)).then(setInv);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const onAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !inv) return;
    try {
      await api.attachInvoiceFile(inv.id, file);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Upload failed");
    }
    e.target.value = "";
  };

  const onApprove = async () => {
    if (!inv) return;
    try {
      await api.approve(inv.id);
      await api.triggerProcess();
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Approve failed");
    }
  };

  if (!inv) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const canApprove =
    inv.has_stored_file &&
    (inv.status === "exception" || inv.status === "duplicate_skipped");

  return (
    <div>
      <PageHeader
        title={invId(inv.id)}
        subtitle={inv.vendor ?? "Invoice detail"}
        actions={
          <>
            {canApprove && (
              <Button size="sm" onClick={onApprove}>
                Approve & process
              </Button>
            )}
            <Link to="/approvals" className="text-sm text-primary hover:underline self-center">
              ← Approvals
            </Link>
          </>
        }
      />

      {!inv.has_stored_file && (
        <Card className="p-4 mb-4 border-dashed border-destructive/40 bg-destructive/5">
          <p className="text-sm font-medium text-destructive mb-1">No stored file</p>
          <p className="text-xs text-muted-foreground mb-3">
            This invoice has no PDF on disk or blob. Upload the original attachment before
            approve or reprocess.
          </p>
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
            <Upload className="h-4 w-4" />
            Upload PDF
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.docx"
              className="hidden"
              onChange={onAttach}
            />
          </label>
        </Card>
      )}

      <div className="mb-4">
        <StageBadge stage={invoiceStage(inv.status)} />
      </div>

      {inv.has_stored_file && (
        <Card className="mb-4 overflow-hidden p-0">
          <InvoiceDocumentViewer invoiceId={inv.id} className="min-h-[28rem]" />
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold">Header</h3>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Vendor</dt>
            <dd>{inv.vendor ?? "—"}</dd>
            <dt className="text-muted-foreground">ABN</dt>
            <dd className="tnum">{inv.abn ?? "—"}</dd>
            <dt className="text-muted-foreground">Invoice #</dt>
            <dd>{inv.invoice_no ?? "—"}</dd>
            <dt className="text-muted-foreground">GL</dt>
            <dd>
              {inv.account_code} {inv.account_name}
            </dd>
            <dt className="text-muted-foreground">Total</dt>
            <dd className="tnum font-semibold">{money(inv.total)}</dd>
          </dl>
        </Card>

        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold">Validation</h3>
          <ul className="space-y-1 text-sm">
            {(inv.validation_results ?? []).length === 0 && (
              <li className="text-muted-foreground">No validation results yet.</li>
            )}
            {(inv.validation_results ?? []).map((v) => (
              <li key={v.rule} className={v.passed ? "text-[hsl(var(--chart-1))]" : "text-destructive"}>
                {v.rule}: {v.message}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card className="mt-4 overflow-hidden">
        <h3 className="border-b border-border px-5 py-3 text-sm font-semibold">Journal entries</h3>
        {inv.journal_entries.length === 0 ? (
          <p className="p-5 text-sm text-muted-foreground">No journal lines yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="px-3 py-2.5 font-medium">Account</th>
                <th className="px-3 py-2.5 font-medium text-right">Debit</th>
                <th className="px-3 py-2.5 font-medium text-right">Credit</th>
              </tr>
            </thead>
            <tbody>
              {inv.journal_entries.map((j) => (
                <tr key={j.id} className="row-band border-b border-border last:border-0">
                  <td className="px-3 py-2.5">
                    {j.account_code} {j.account_name}
                  </td>
                  <td className="px-3 py-2.5 tnum text-right">{money(j.debit)}</td>
                  <td className="px-3 py-2.5 tnum text-right">{money(j.credit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
