import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { InvoiceDetails, PaymentApi } from "@/api/types";
import { formatMoney, invoiceTaxMeta } from "@/components/invoice-preview/DocumentSummaryPreview";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import {
  groupJournalEntries,
  invoiceAccountingPostingStatus,
  paymentStatusDisplay,
  summarizeLineGlCoding,
} from "@/lib/invoiceAccounting";

type InvoiceDrawerAccountingSectionProps = {
  inv: InvoiceDetails;
  parentLedger: string;
  currencySymbolHint?: string | null;
  payment: PaymentApi | null;
  paymentLoading: boolean;
};

function toneClass(tone: "muted" | "pending" | "success" | "error"): string {
  if (tone === "success") return "text-emerald-700 dark:text-emerald-400";
  if (tone === "error") return "text-destructive";
  if (tone === "pending") return "text-amber-700 dark:text-amber-400";
  return "text-muted-foreground";
}

function SectionCard({
  title,
  children,
  testId,
}: {
  title: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section
      className="rounded-lg border border-border bg-card/40"
      data-testid={testId}
    >
      <h3 className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <div className="px-3 py-3">{children}</div>
    </section>
  );
}

function SummaryRow({
  label,
  value,
  emphasize = false,
}: {
  label: string;
  value: ReactNode;
  emphasize?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className={cn("text-right", emphasize && "font-medium text-foreground")}>
        {value}
      </span>
    </div>
  );
}

export function InvoiceDrawerAccountingSection({
  inv,
  parentLedger,
  currencySymbolHint,
  payment,
  paymentLoading,
}: InvoiceDrawerAccountingSectionProps) {
  const posting = invoiceAccountingPostingStatus(inv);
  const tax = invoiceTaxMeta(inv);
  const fmt = (value: string | null | undefined) =>
    inv.currency
      ? formatMoney(value, inv.currency, undefined, currencySymbolHint)
      : money(value, inv.currency);
  const lineCoding = summarizeLineGlCoding(inv.line_items, parentLedger);
  const journalGroups = groupJournalEntries(inv.journal_entries);
  const paymentSummary = paymentStatusDisplay(payment);

  const headerGl =
    [inv.account_code, inv.account_name].filter(Boolean).join(" ").trim() ||
    parentLedger ||
    "—";

  return (
    <div className="mt-4 space-y-4" data-testid="invoice-drawer-accounting-tab">
      <SectionCard title="Posting status" testId="invoice-accounting-posting-status">
        <p className={cn("text-sm font-medium", toneClass(posting.tone))}>{posting.label}</p>
        <p className="mt-1 text-xs text-muted-foreground">{posting.detail}</p>
        {inv.invoice_date ? (
          <p className="mt-2 text-xs text-muted-foreground">
            Accrual date: {inv.invoice_date}
          </p>
        ) : null}
      </SectionCard>

      <SectionCard title="GL coding" testId="invoice-accounting-gl">
        <SummaryRow label="Header Post To" value={headerGl} emphasize />
        {lineCoding.length === 0 ? (
          <p className="mt-3 text-xs text-muted-foreground">
            No line items yet — GL split will appear after extraction.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="invoice-drawer-lines-table invoice-drawer-lines-table--readonly w-full min-w-[28rem] text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="pb-2 pr-2 font-medium">Line</th>
                  <th className="pb-2 pr-2 font-medium">Main GL</th>
                  <th className="pb-2 pr-2 font-medium">Sub GL</th>
                  <th className="pb-2 font-medium text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {lineCoding.map((row, index) => {
                  const line = inv.line_items[index];
                  return (
                    <tr key={row.key} className="border-t border-border/60">
                      <td className="py-2 pr-2 align-top">{row.description}</td>
                      <td className="py-2 pr-2 align-top">{row.mainGl}</td>
                      <td className="py-2 pr-2 align-top">{row.subGl}</td>
                      <td className="py-2 tnum text-right align-top">
                        {fmt(line?.amount)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-muted-foreground">
          Edit line GL accounts on the Line items tab while the invoice is in review.
        </p>
      </SectionCard>

      <SectionCard title="Tax & amounts" testId="invoice-accounting-tax">
        <div className="space-y-2">
          <SummaryRow label="Subtotal (ex-tax)" value={fmt(inv.subtotal)} />
          <SummaryRow
            label={tax.rate != null ? `${tax.label} ${tax.rate}%` : tax.label}
            value={fmt(inv.gst)}
          />
          <div className="border-t border-border my-2" />
          <SummaryRow label="Total (inc-tax)" value={fmt(inv.total)} emphasize />
          <SummaryRow
            label="Currency"
            value={inv.currency?.trim().toUpperCase() || "—"}
          />
        </div>
      </SectionCard>

      <SectionCard title="Journal entries" testId="invoice-accounting-journals">
        {journalGroups.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No journal lines yet — entries are created when this invoice posts.
          </p>
        ) : (
          <div className="space-y-4">
            {journalGroups.map((group) => (
              <div key={group.id}>
                <p className="mb-2 text-xs font-medium text-foreground">{group.title}</p>
                <div className="overflow-x-auto">
                  <table className="invoice-drawer-lines-table invoice-drawer-lines-table--readonly w-full min-w-[24rem] text-xs">
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="pb-2 pr-2 font-medium">Account</th>
                        <th className="pb-2 pr-2 font-medium text-right">Debit</th>
                        <th className="pb-2 font-medium text-right">Credit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.entries.map((entry) => (
                        <tr key={entry.id} className="border-t border-border/60">
                          <td className="py-2 pr-2">
                            {[entry.account_code, entry.account_name]
                              .filter(Boolean)
                              .join(" ")
                              .trim() || "—"}
                          </td>
                          <td className="py-2 pr-2 tnum text-right">
                            {fmt(entry.debit)}
                          </td>
                          <td className="py-2 tnum text-right">
                            {fmt(entry.credit)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Payment" testId="invoice-accounting-payment">
        {paymentLoading ? (
          <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading payment…
          </p>
        ) : (
          <div className="space-y-2">
            <SummaryRow label="Status" value={paymentSummary.label} emphasize />
            <p className="text-xs text-muted-foreground">{paymentSummary.detail}</p>
            {payment?.due_date ? (
              <SummaryRow label="Due date" value={payment.due_date} />
            ) : inv.due_date ? (
              <SummaryRow label="Due date" value={inv.due_date} />
            ) : null}
            {payment ? (
              <SummaryRow label="Amount" value={fmt(String(payment.amount))} />
            ) : null}
            {payment ? (
              <Link
                to="/payments"
                className="inline-block pt-1 text-xs font-medium text-primary hover:underline"
                data-testid="invoice-accounting-open-payments"
              >
                Open payments workspace
              </Link>
            ) : null}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
