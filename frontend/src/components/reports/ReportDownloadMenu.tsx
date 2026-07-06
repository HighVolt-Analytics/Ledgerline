import { useState, type ReactNode } from "react";
import { Download } from "lucide-react";
import { api } from "@/api/client";
import type { ReportsAnalytics } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
import {
  downloadDocumentRegisterCsv,
  downloadGlSummaryCsv,
  downloadVendorSummaryCsv,
  monthToDateRange,
} from "@/lib/reportExports";

export type ReportDownloadKind =
  | "workbook"
  | "documents"
  | "documents-bundle"
  | "gl"
  | "vendors"
  | "audit"
  | "workbook-custom";

const TYPE_OPTIONS: SelectOption[] = [
  { value: "workbook", label: "Excel workbook" },
  { value: "documents", label: "Document register (CSV)" },
  { value: "documents-bundle", label: "Documents bundle (CSV)" },
  { value: "gl", label: "GL account summary (CSV)" },
  { value: "vendors", label: "Top vendors (CSV)" },
  { value: "audit", label: "Audit trail (CSV)" },
  { value: "workbook-custom", label: "Excel workbook (custom range…)" },
];

type ReportDownloadMenuProps = {
  month: string;
  analytics: ReportsAnalytics | undefined;
  periodSelector: ReactNode;
  disabled?: boolean;
  onCustomWorkbook: () => void;
  onToast: (message: string) => void;
};

export function ReportDownloadMenu({
  month,
  analytics,
  periodSelector,
  disabled,
  onCustomWorkbook,
  onToast,
}: ReportDownloadMenuProps) {
  const [kind, setKind] = useState<ReportDownloadKind>("workbook");
  const [busy, setBusy] = useState(false);

  async function handleDownload() {
    if (!month || busy) return;

    if (kind === "workbook-custom") {
      onCustomWorkbook();
      return;
    }

    setBusy(true);
    try {
      const filter = monthToDateRange(month);

      switch (kind) {
        case "workbook": {
          const { filename } = await api.generateReport(filter);
          await api.downloadReport(filter, filename);
          onToast("Excel workbook downloaded.");
          break;
        }
        case "documents": {
          const rows = await api.getReportDocuments(filter);
          if (rows.length === 0) {
            onToast("No documents in this period to export.");
            return;
          }
          downloadDocumentRegisterCsv(rows, month);
          onToast("Document register downloaded.");
          break;
        }
        case "documents-bundle": {
          const { dataRows } = await api.downloadDocumentsBundleCsv(
            filter.dateFrom,
            filter.dateTo
          );
          if (dataRows === 0) {
            onToast("No transactional posting documents in this period to export.");
            return;
          }
          onToast("Documents bundle downloaded.");
          break;
        }
        case "gl": {
          if (!analytics?.by_gl_account?.length) {
            onToast("No GL data for this period.");
            return;
          }
          downloadGlSummaryCsv(analytics, month);
          onToast("GL summary downloaded.");
          break;
        }
        case "vendors": {
          if (!analytics?.top_vendors?.length) {
            onToast("No vendor data for this period.");
            return;
          }
          downloadVendorSummaryCsv(analytics, month);
          onToast("Vendor summary downloaded.");
          break;
        }
        case "audit": {
          await api.downloadAuditLogCsv(month);
          onToast("Audit trail downloaded.");
          break;
        }
        default:
          break;
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Select
        value={kind}
        onValueChange={(value) => setKind(value as ReportDownloadKind)}
        options={TYPE_OPTIONS}
        disabled={disabled || busy}
        data-testid="select-report-download-type"
        className="min-w-[11rem]"
      />
      {periodSelector}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || busy || !month}
        data-testid="button-report-download"
        onClick={() => void handleDownload()}
      >
        <Download className="h-4 w-4 mr-1" />
        {busy ? "Downloading…" : "Download"}
      </Button>
    </div>
  );
}
