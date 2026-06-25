import { Building2, Calendar, Check, FileText, Layers, X } from 'lucide-react';

export default function PaymentInvoiceCard() {
  return (
    <div className="payment-invoice-shell">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Layers className="h-4 w-4 shrink-0 text-primary/80" />
        <span className="font-medium text-foreground/90">3-way match passed</span>
        <span className="text-muted-foreground/60">·</span>
        <span>Control C2 cleared</span>
      </div>

      <div className="payment-invoice-card mt-4">
        <div className="flex items-center gap-3">
          <div className="payment-invoice-avatar">MK</div>
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-foreground">Metro Kitchen Supplies</p>
            <p className="truncate text-sm text-muted-foreground">Acme Hospitality · Sydney AU</p>
          </div>
        </div>

        <p className="mt-5 text-3xl font-semibold tracking-tight text-foreground sm:text-[2rem]">A$ 6,150.00</p>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="payment-invoice-badge payment-invoice-badge--match">100% match</span>
          <span className="payment-invoice-badge payment-invoice-badge--type">
            <Building2 className="h-3.5 w-3.5" />
            AP Invoice
          </span>
          <span className="payment-invoice-badge payment-invoice-badge--meta">
            <FileText className="h-3.5 w-3.5" />
            PO-0042
          </span>
          <span className="payment-invoice-badge payment-invoice-badge--meta">
            <Calendar className="h-3.5 w-3.5" />
            Due Mar 14
          </span>
        </div>

        <p className="mt-4 text-sm leading-relaxed text-foreground/85">
          Approved invoice with PO and GRN matched within tolerance. Queued for payment on the scheduled date.
        </p>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <button type="button" className="payment-invoice-action payment-invoice-action--secondary">
          <X className="h-4 w-4" />
          Hold
        </button>
        <button type="button" className="payment-invoice-action payment-invoice-action--primary">
          <Check className="h-4 w-4" strokeWidth={3} />
          Pay now
        </button>
      </div>

      <div className="payment-invoice-stack" aria-hidden="true">
        <span />
        <span />
      </div>
    </div>
  );
}
