import { useMemo } from "react";

import { FileText } from "lucide-react";

import type { InvoiceDetails, LineItem } from "@/api/types";

import { counterpartyUnknownLabel } from "@/lib/invoice";

import {
  buildDocumentContentProfile,
  formatPreviewMoney,
  invoiceTaxMeta,
  isCompactReceiptStyle,
  taxMetaForCurrency,
  taxMetaForJurisdiction,
  type ContentReference,
  type DocumentContentProfile,
  type PartyPreviewBlock,
} from "@/lib/invoicePreview";
import { counterpartyLabel } from "@/lib/invoice";

import { cn } from "@/lib/cn";



export type DocumentSummaryPreviewProps = {

  inv: InvoiceDetails;

  lineItems?: LineItem[];

  documentTypeLabel: string | null;

  absentFields?: string[];

  /** User-defined DT extraction fields — guide supplementary summary blocks (optional, never mandatory). */

  extractionFieldKeys?: string[];

  fmt: (value: string | null | undefined) => string;

  tax: { label: string; rate: number | null };

  sourceKind: string;

};



function PreviewKeyValueRow({

  label,

  value,

  className,

  stacked = false,

}: {

  label: string;

  value: string;

  className?: string;

  stacked?: boolean;

}) {

  return (

    <div

      className={cn(

        "invoice-preview-kv-row",

        stacked && "invoice-preview-kv-row--stacked",

        className

      )}

    >

      <span className="invoice-preview-kv-label">{label}</span>

      <span className="invoice-preview-kv-value tnum">{value}</span>

    </div>

  );

}



function shouldShowPartySection(profile: DocumentContentProfile, compact: boolean): boolean {

  if (!profile.parties.length) return false;

  if (!compact) return true;

  return profile.parties.some((party) => party.taxId || party.address);

}



function PreviewPartyCard({ party }: { party: PartyPreviewBlock }) {

  return (

    <div className="invoice-preview-party-card">

      <div className="invoice-preview-section-title">{party.label}</div>

      {party.name && (

        <div className="invoice-preview-party-name">{party.name}</div>

      )}

      {party.taxId && (

        <div className="invoice-preview-party-meta tnum">Tax ID {party.taxId}</div>

      )}

      {party.address && (

        <div className="invoice-preview-party-address">{party.address}</div>

      )}

    </div>

  );

}



function PreviewPartySection({

  profile,

  compact,

}: {

  profile: DocumentContentProfile;

  compact: boolean;

}) {

  if (!shouldShowPartySection(profile, compact)) return null;



  const pair = profile.parties.length > 1;

  return (

    <section className="invoice-preview-section invoice-preview-parties-wrap">

      <div

        className={cn(

          "invoice-preview-parties",

          pair && "invoice-preview-parties--pair"

        )}

      >

        {profile.parties.map((party) => (

          <PreviewPartyCard key={party.key} party={party} />

        ))}

      </div>

    </section>

  );

}



function PreviewReferenceSection({ profile }: { profile: DocumentContentProfile }) {

  if (!profile.referenceDetails.length) return null;



  return (

    <section className="invoice-preview-section">

      <div className="invoice-preview-section-title">Details</div>

      <div className="invoice-preview-kv-list">

        {profile.referenceDetails.map((detail) => (

          <PreviewReferenceRow key={detail.key} reference={detail} />

        ))}

      </div>

    </section>

  );

}



function PreviewReferenceRow({ reference }: { reference: ContentReference }) {

  const stacked = reference.value.length > 60 || reference.key === "billing_address";

  return (

    <PreviewKeyValueRow

      label={reference.label}

      value={reference.value}

      stacked={stacked}

    />

  );

}



function PreviewLineItemsTable({

  profile,

  fmt,

}: {

  profile: DocumentContentProfile;

  fmt: (value: string | null | undefined) => string;

}) {

  if (!profile.lineItems.length) return null;



  const { showQty, showUnitPrice, showAmount } = profile.lineItemColumns;



  return (

    <table

      className={cn(

        "invoice-preview-table text-xs",

        showUnitPrice && "invoice-preview-table--with-unit-price"

      )}

    >

      <thead>

        <tr className="border-b border-border text-muted-foreground">

          <th className="text-left py-2 font-medium">Description</th>

          {showQty && <th className="text-right py-2 font-medium">Qty</th>}

          {showUnitPrice && <th className="text-right py-2 font-medium">Unit price</th>}

          {showAmount && <th className="text-right py-2 font-medium">Amount</th>}

        </tr>

      </thead>

      <tbody>

        {profile.lineItems.map((line) => (

          <tr key={line.id} className="border-b border-border/60">

            <td className="py-2.5 align-top">{line.description ?? "—"}</td>

            {showQty && (

              <td className="py-2.5 align-top tnum text-right">

                {line.displayQty ?? ""}

              </td>

            )}

            {showUnitPrice && (

              <td className="py-2.5 align-top tnum text-right">

                {line.displayUnitPrice ? fmt(line.displayUnitPrice) : ""}

              </td>

            )}

            {showAmount && (

              <td className="py-2.5 align-top tnum text-right">

                {line.displayAmount ? fmt(line.displayAmount) : ""}

              </td>

            )}

          </tr>

        ))}

      </tbody>

    </table>

  );

}



function PreviewTotalsBlock({

  profile,

  fmt,

  tax,

  compact,

}: {

  profile: DocumentContentProfile;

  fmt: (value: string | null | undefined) => string;

  tax: { label: string; rate: number | null };

  compact: boolean;

}) {

  const { subtotal, tax: taxAmount, total } = profile.totals;

  if (!subtotal && !taxAmount && !total) return null;

  const totalLabel = profile.currency ? `Total (${profile.currency})` : "Total";



  if (compact && total && !subtotal && !taxAmount) {

    return (

      <div className="invoice-preview-totals invoice-preview-totals--emphasis">

        <PreviewKeyValueRow

          label={totalLabel}

          value={fmt(total)}

          className="invoice-preview-kv-row--total"

        />

      </div>

    );

  }



  return (

    <div className="invoice-preview-totals">

      {subtotal && (

        <PreviewKeyValueRow label="Subtotal" value={fmt(subtotal)} />

      )}

      {taxAmount && (

        <PreviewKeyValueRow

          label={tax.rate != null ? `${tax.label} ${tax.rate}%` : tax.label}

          value={fmt(taxAmount)}

        />

      )}

      {total && (

        <PreviewKeyValueRow

          label={totalLabel}

          value={fmt(total)}

          className="invoice-preview-kv-row--total"

        />

      )}

    </div>

  );

}



export function DocumentSummaryPreview({

  inv,

  lineItems,

  documentTypeLabel,

  absentFields: _absentFields = [],

  extractionFieldKeys: _extractionFieldKeys = [],

  fmt,

  tax,

  sourceKind,

}: DocumentSummaryPreviewProps) {

  const profile = useMemo(

    () =>

      buildDocumentContentProfile(inv, {

        documentTypeLabel,

        sourceKind,

        lineItems,

        summaryMode: true,

      }),

    [inv, lineItems, documentTypeLabel, sourceKind]

  );



  const compact = isCompactReceiptStyle(profile);

  const counterparty = profile.counterparty || counterpartyUnknownLabel(inv);

  const counterpartyRole = counterpartyLabel(inv);

  const heading = profile.heading || "Document";

  const hasBody =

    Boolean(profile.counterparty) ||

    Boolean(profile.invoiceNo) ||

    Boolean(profile.abn) ||

    Boolean(profile.heading) ||

    profile.lineItems.length > 0 ||

    Boolean(profile.totals.subtotal || profile.totals.tax || profile.totals.total) ||

    profile.parties.length > 0 ||

    profile.referenceDetails.length > 0 ||

    profile.dates.issued ||

    profile.dates.due ||

    profile.bankDetails ||

    profile.textExcerpt;



  return (

    <div

      className={cn(

        "invoice-preview-card",

        compact && "invoice-preview-card--compact"

      )}

    >

      <header className="invoice-preview-header">

        <div className="invoice-preview-header-main min-w-0">

          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">

            {counterpartyRole}

          </div>

          <div className="invoice-preview-vendor">{counterparty}</div>

          {profile.abn && (

            <div className="invoice-preview-abn tnum">{profile.abn}</div>

          )}

          {profile.emailSender && (

            <div className="invoice-preview-email">{profile.emailSender}</div>

          )}

        </div>

        <div className="invoice-preview-header-aside shrink-0">

          <div className="invoice-preview-doc-type">{heading}</div>

          {profile.invoiceNo && (

            <div className="invoice-preview-invoice-no tnum">{profile.invoiceNo}</div>

          )}

          {profile.dates.issued && (

            <div className="invoice-preview-header-date tnum">

              Issued {profile.dates.issued}

            </div>

          )}

          {profile.dates.due && (

            <div className="invoice-preview-header-date tnum">

              Due {profile.dates.due}

            </div>

          )}

          {documentTypeLabel && documentTypeLabel !== heading && (

            <div className="text-[10px] text-muted-foreground mt-1">{documentTypeLabel}</div>

          )}

          <div className="invoice-preview-doc-ref tnum">{profile.docRef}</div>

        </div>

      </header>



      <PreviewPartySection profile={profile} compact={compact} />



      <PreviewReferenceSection profile={profile} />



      <PreviewLineItemsTable profile={profile} fmt={fmt} />



      <PreviewTotalsBlock profile={profile} fmt={fmt} tax={tax} compact={compact} />



      {profile.bankDetails && (

        <div className="invoice-preview-kv-list invoice-preview-section">

          <PreviewKeyValueRow label="Bank details" value={profile.bankDetails} />

        </div>

      )}



      {profile.textExcerpt && (

        <div className="invoice-preview-excerpt invoice-preview-section">

          <div className="invoice-preview-section-title">Document text</div>

          <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">

            {profile.textExcerpt}

          </p>

        </div>

      )}



      {profile.pipelineKind === "vision_header" && (

        <p className="text-[11px] text-muted-foreground px-1 pt-1">

          Vision path — header fields only; catalogue document type not mapped yet.

        </p>

      )}



      {!hasBody && (

        <p className="invoice-preview-empty">

          {profile.pipelineKind === "vision_header"

            ? (inv.evaluation_status ?? "").trim() === "vision_header_review"

              ? "Header extract incomplete — open Original, fix Fields, then reprocess."

              : (inv.evaluation_status ?? "").trim() === "vision_vaulted"

                ? "Understood path vaulted — header fields should appear above; reprocess if Summary is empty."

                : "No header fields extracted yet — open Original to view the file, or reprocess after vision is configured."

            : "No structured fields extracted yet — open Original to view the uploaded file, or check Document text above if OCR is available."}

        </p>

      )}



      <footer className="invoice-preview-footer">

        <FileText className="h-3 w-3 shrink-0" aria-hidden />

        <span>{profile.footer}</span>

      </footer>

    </div>

  );

}



export {
  formatPreviewMoney as formatMoney,
  invoiceTaxMeta,
  taxMetaForCurrency as taxMeta,
  taxMetaForJurisdiction,
};

