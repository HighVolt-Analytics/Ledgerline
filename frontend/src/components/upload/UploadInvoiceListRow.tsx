import type { Invoice } from "@/api/types";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import {
  DuplicateReviewBadge,
  EvaluationStatusBadge,
  RouteTargetBadge,
} from "@/components/inbox/EvaluationStatusBadge";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { invoiceStageBadgeProps, StageBadge } from "@/components/StageBadge";
import { UploadColumnCell } from "@/components/upload/UploadColumnCell";
import { documentDisplayRef, money } from "@/lib/format";
import { invoiceDocumentTypeDisplayLabel } from "@/lib/documentTypeResolve";
import {
  counterpartyMatchLabel,
  counterpartyName,
  invoiceCounterpartyConfidence,
  invoiceValidationConfidence,
  invoiceVaultFolderLabel,
  vendorMatchApplicable,
} from "@/lib/invoice";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  isStageColumnProcessing,
  uploadColumnDisplayMode,
  type ColumnDisplayMode,
  type UploadListColumnId,
} from "@/lib/uploadColumnState";

export type UploadInvoiceRowProps = {
  inv: Invoice;
  documentTypes?: DocumentTypeDefinition[] | null;
  processingIds?: ReadonlySet<number>;
  onOpen: () => void;
  receivedLabel: string;
};

function rowColumnModes(
  inv: Invoice,
  documentTypes?: DocumentTypeDefinition[] | null,
  processingIds?: ReadonlySet<number>
): Record<UploadListColumnId, ColumnDisplayMode> {
  const opts = { processingIds, documentTypes };
  return {
    documentMeta: uploadColumnDisplayMode(inv, "documentMeta", opts),
    documentType: uploadColumnDisplayMode(inv, "documentType", opts),
    counterparty: uploadColumnDisplayMode(inv, "counterparty", opts),
    route: uploadColumnDisplayMode(inv, "route", opts),
    glAccount: uploadColumnDisplayMode(inv, "glAccount", opts),
    evaluation: uploadColumnDisplayMode(inv, "evaluation", opts),
    vrPass: uploadColumnDisplayMode(inv, "vrPass", opts),
    match: uploadColumnDisplayMode(inv, "match", opts),
    total: uploadColumnDisplayMode(inv, "total", opts),
  };
}

function DocumentMetaLine({
  inv,
  mode,
}: {
  inv: Invoice;
  mode: ColumnDisplayMode;
}) {
  return (
    <UploadColumnCell mode={mode} className="text-xs text-muted-foreground tnum">
      {inv.invoice_no ? <span className="truncate">{inv.invoice_no}</span> : null}
    </UploadColumnCell>
  );
}

function DocumentTypeLine({
  inv,
  documentTypes,
  mode,
}: {
  inv: Invoice;
  documentTypes?: DocumentTypeDefinition[] | null;
  mode: ColumnDisplayMode;
}) {
  // Chip code = stored DT only. Invented purchase-kind codes make early rows look classified.
  const code = (inv.document_type_code ?? "").trim();
  const typeLabel = invoiceDocumentTypeDisplayLabel(inv, documentTypes);

  return (
    <UploadColumnCell mode={mode}>
      <DocumentTypeChip
        code={code}
        label={typeLabel}
        display={typeLabel}
        title={typeLabel}
        purchaseKind={inv.purchase_document_type}
        documentTypes={documentTypes}
      />
    </UploadColumnCell>
  );
}

export function UploadInvoiceMobileRow({
  inv,
  documentTypes,
  processingIds,
  onOpen,
  receivedLabel,
}: UploadInvoiceRowProps) {
  const modes = rowColumnModes(inv, documentTypes, processingIds);
  const stageProps = invoiceStageBadgeProps(inv);
  const stageProcessing = isStageColumnProcessing(inv, processingIds);
  const matchLabel = counterpartyMatchLabel(inv, documentTypes);
  const showMatch =
    matchLabel != null || vendorMatchApplicable(inv, documentTypes);
  const stageTitle = (inv.resolution_hint ?? "").trim() || undefined;

  return (
    <button
      type="button"
      data-testid={`row-invoice-${inv.id}`}
      className="w-full text-left px-3 py-3 hover-elevate active:bg-muted/40 transition-colors"
      onClick={onOpen}
    >
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0 flex-1">
          <div className="font-medium tnum">{documentDisplayRef(inv)}</div>
          <DocumentMetaLine inv={inv} mode={modes.documentMeta} />
          <div className="mt-1">
            <DocumentTypeLine inv={inv} documentTypes={documentTypes} mode={modes.documentType} />
          </div>
          <UploadColumnCell mode={modes.counterparty} className="text-sm truncate mt-0.5 block">
            {counterpartyName(inv)}
          </UploadColumnCell>
        </div>
        <div className="shrink-0 text-right">
          <UploadColumnCell
            mode={modes.total}
            align="right"
            className="tnum font-medium text-sm block"
          >
            {money(inv.total, inv.currency)}
          </UploadColumnCell>
          <div className="text-[11px] text-muted-foreground tnum mt-0.5">{receivedLabel}</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 mt-2">
        <UploadColumnCell mode={modes.route}>
          <RouteTargetBadge route={invoiceVaultFolderLabel(inv) || null} />
        </UploadColumnCell>
        <UploadColumnCell mode={modes.glAccount}>
          <InboxGlAccountBadge
            account={inv.account_name}
            glPostingApplicable={inv.gl_posting_applicable ?? true}
          />
        </UploadColumnCell>
        <StageBadge {...stageProps} processing={stageProcessing} title={stageTitle} />
        <UploadColumnCell mode={modes.evaluation}>
          <div className="flex flex-col items-start gap-1">
            <EvaluationStatusBadge status={inv.evaluation_status} invoice={inv} />
            <DuplicateReviewBadge suggested={inv.duplicate_review_suggested} />
          </div>
        </UploadColumnCell>
      </div>
      <div className="flex flex-wrap items-center gap-3 mt-1.5 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          Rule pass
          <UploadColumnCell mode={modes.vrPass}>
            <InboxConfidenceBadge
              value={invoiceValidationConfidence(inv, documentTypes)}
            />
          </UploadColumnCell>
        </span>
        {showMatch ? (
          <span className="inline-flex items-center gap-1">
            {matchLabel ?? "Master match"}
            <UploadColumnCell mode={modes.match}>
              <InboxConfidenceBadge
                value={invoiceCounterpartyConfidence(inv, documentTypes)}
              />
            </UploadColumnCell>
          </span>
        ) : null}
      </div>
    </button>
  );
}

export function UploadInvoiceTableRow({
  inv,
  documentTypes,
  processingIds,
  onOpen,
  receivedLabel,
}: UploadInvoiceRowProps) {
  const modes = rowColumnModes(inv, documentTypes, processingIds);
  const stageProps = invoiceStageBadgeProps(inv);
  const stageProcessing = isStageColumnProcessing(inv, processingIds);
  const vaultFolder = invoiceVaultFolderLabel(inv);
  const stageTitle = (inv.resolution_hint ?? "").trim() || undefined;

  return (
    <tr
      data-testid={`row-invoice-${inv.id}`}
      className="row-band border-b border-border/60 cursor-pointer hover-elevate last:border-0"
      onClick={onOpen}
    >
      <td className="px-4 py-2.5">
        <div className="font-medium tnum">{documentDisplayRef(inv)}</div>
        <DocumentMetaLine inv={inv} mode={modes.documentMeta} />
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        <DocumentTypeLine inv={inv} documentTypes={documentTypes} mode={modes.documentType} />
      </td>
      <td className="px-3 py-2.5 max-w-[160px] truncate">
        <UploadColumnCell mode={modes.counterparty}>{counterpartyName(inv)}</UploadColumnCell>
      </td>
      <td className="px-3 py-2.5">
        <UploadColumnCell mode={modes.route}>
          <RouteTargetBadge route={vaultFolder || null} />
        </UploadColumnCell>
      </td>
      <td className="px-3 py-2.5">
        <UploadColumnCell mode={modes.glAccount}>
          <InboxGlAccountBadge
            account={inv.account_name}
            glPostingApplicable={inv.gl_posting_applicable ?? true}
          />
        </UploadColumnCell>
      </td>
      <td className="px-3 py-2.5">
        <StageBadge {...stageProps} processing={stageProcessing} title={stageTitle} />
      </td>
      <td className="px-3 py-2.5">
        <UploadColumnCell mode={modes.evaluation}>
          <div className="flex flex-col items-start gap-1">
            <EvaluationStatusBadge status={inv.evaluation_status} invoice={inv} />
            <DuplicateReviewBadge suggested={inv.duplicate_review_suggested} />
          </div>
        </UploadColumnCell>
      </td>
      <td className="px-3 py-2.5 text-right">
        <UploadColumnCell mode={modes.vrPass} align="right">
          <InboxConfidenceBadge value={invoiceValidationConfidence(inv, documentTypes)} />
        </UploadColumnCell>
      </td>
      <td className="px-3 py-2.5 text-right">
        <UploadColumnCell mode={modes.match} align="right">
          <InboxConfidenceBadge value={invoiceCounterpartyConfidence(inv, documentTypes)} />
        </UploadColumnCell>
      </td>
      <td className="px-3 py-2.5 text-right tnum font-medium whitespace-nowrap">
        <UploadColumnCell mode={modes.total} align="right">
          {money(inv.total, inv.currency)}
        </UploadColumnCell>
      </td>
      <td className="px-4 py-2.5 text-right text-xs text-muted-foreground tnum whitespace-nowrap">
        {receivedLabel}
      </td>
    </tr>
  );
}
