import type { Invoice } from "@/api/types";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";
import {
  EvaluationStatusBadge,
  RouteTargetBadge,
} from "@/components/inbox/EvaluationStatusBadge";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { InboxSourceBadge } from "@/components/inbox/InboxSourceBadge";
import { invoiceStageBadgeProps, StageBadge } from "@/components/StageBadge";
import { UploadColumnCell } from "@/components/upload/UploadColumnCell";
import { documentDisplayRef, money } from "@/lib/format";
import { invoiceDocumentTypeDisplayLabel } from "@/lib/documentTypeResolve";
import {
  counterpartyMatchLabel,
  counterpartyName,
  invoiceCounterpartyConfidence,
  invoiceSourceKind,
  invoiceValidationConfidence,
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
  documentTypes,
  mode,
}: {
  inv: Invoice;
  documentTypes?: DocumentTypeDefinition[] | null;
  mode: ColumnDisplayMode;
}) {
  const typeLabel = invoiceDocumentTypeDisplayLabel(inv, documentTypes);
  const metaText = [inv.invoice_no, typeLabel].filter(Boolean).join(" · ");

  return (
    <UploadColumnCell mode={mode} className="text-xs text-muted-foreground tnum truncate">
      {metaText || "—"}
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
          <DocumentMetaLine inv={inv} documentTypes={documentTypes} mode={modes.documentMeta} />
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
        <InboxSourceBadge kind={invoiceSourceKind(inv)} />
        <UploadColumnCell mode={modes.route}>
          <RouteTargetBadge route={inv.route_target} />
        </UploadColumnCell>
        <UploadColumnCell mode={modes.glAccount}>
          <InboxGlAccountBadge
            account={inv.account_name}
            glPostingApplicable={inv.gl_posting_applicable ?? true}
          />
        </UploadColumnCell>
        <StageBadge {...stageProps} processing={stageProcessing} />
        <UploadColumnCell mode={modes.evaluation}>
          <EvaluationStatusBadge status={inv.evaluation_status} />
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

  return (
    <tr
      data-testid={`row-invoice-${inv.id}`}
      className="row-band border-b border-border/60 cursor-pointer hover-elevate last:border-0"
      onClick={onOpen}
    >
      <td className="px-4 py-2.5">
        <div className="font-medium tnum">{documentDisplayRef(inv)}</div>
        <DocumentMetaLine inv={inv} documentTypes={documentTypes} mode={modes.documentMeta} />
      </td>
      <td className="px-3 py-2.5 max-w-[160px] truncate">
        <UploadColumnCell mode={modes.counterparty}>{counterpartyName(inv)}</UploadColumnCell>
      </td>
      <td className="px-3 py-2.5">
        <InboxSourceBadge kind={invoiceSourceKind(inv)} />
      </td>
      <td className="px-3 py-2.5">
        <UploadColumnCell mode={modes.route}>
          <RouteTargetBadge route={inv.route_target} />
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
        <StageBadge {...stageProps} processing={stageProcessing} />
      </td>
      <td className="px-3 py-2.5">
        <UploadColumnCell mode={modes.evaluation}>
          <EvaluationStatusBadge status={inv.evaluation_status} />
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
