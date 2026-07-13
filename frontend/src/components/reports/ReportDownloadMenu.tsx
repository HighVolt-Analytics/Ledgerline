import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { api } from "@/api/client";
import type { ReportsAnalytics } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, type SelectOption } from "@/components/ui/select";
import {
  downloadDocumentRegisterCsv,
  downloadGlSummaryCsv,
  downloadPeriodLabel,
  downloadVendorSummaryCsv,
  monthToDateRange,
  resolveDownloadFilter,
  type ReportDownloadPeriod,
} from "@/lib/reportExports";

export type ReportDownloadKind =
  | "workbook"
  | "documents"
  | "documents-bundle"
  | "gl"
  | "vendors"
  | "audit";

const TYPE_OPTIONS: SelectOption[] = [
  { value: "workbook", label: "Excel workbook" },
  { value: "documents", label: "Document register (CSV)" },
  { value: "documents-bundle", label: "Documents bundle (CSV)" },
  { value: "gl", label: "GL account summary (CSV)" },
  { value: "vendors", label: "Top vendors (CSV)" },
  { value: "audit", label: "Audit trail (CSV)" },
];

const PERIOD_OPTIONS: SelectOption[] = [
  { value: "month", label: "This month" },
  { value: "range", label: "Date range" },
  { value: "all", label: "All dates" },
];

const MONTH_ONLY_KINDS = new Set<ReportDownloadKind>(["gl", "vendors"]);

type ReportDownloadMenuProps = {
  month: string;
  analytics: ReportsAnalytics | undefined;
  disabled?: boolean;
  onToast: (message: string) => void;
};

export function ReportDownloadMenu({
  month,
  analytics,
  disabled,
  onToast,
}: ReportDownloadMenuProps) {
  const [kind, setKind] = useState<ReportDownloadKind>("workbook");
  const [period, setPeriod] = useState<ReportDownloadPeriod>("month");
  const [busy, setBusy] = useState(false);

  const initialRange = useMemo(() => monthToDateRange(month), [month]);
  const [dateFrom, setDateFrom] = useState(initialRange.dateFrom);
  const [dateTo, setDateTo] = useState(initialRange.dateTo);

  const flexiblePeriod = !MONTH_ONLY_KINDS.has(kind);
  const effectivePeriod: ReportDownloadPeriod = flexiblePeriod ? period : "month";
  const rangeInvalid = effectivePeriod === "range" && dateFrom > dateTo;

  function handleKindChange(value: string) {
    const next = value as ReportDownloadKind;
    setKind(next);
    if (MONTH_ONLY_KINDS.has(next)) {
      setPeriod("month");
    }
  }

  function handlePeriodChange(value: string) {
    const next = value as ReportDownloadPeriod;
    if (next === "range") {
      const range = monthToDateRange(month);
      setDateFrom(range.dateFrom);
      setDateTo(range.dateTo);
    }
    setPeriod(next);
  }

  async function handleDownload() {
    if (!month || busy || rangeInvalid) return;

    setBusy(true);
    try {
      const filter = resolveDownloadFilter(effectivePeriod, month, dateFrom, dateTo);
      const label = downloadPeriodLabel(effectivePeriod, month, dateFrom, dateTo);

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
          downloadDocumentRegisterCsv(rows, label);
          onToast("Document register downloaded.");
          break;
        }
        case "documents-bundle": {
          const { dataRows } = await api.downloadDocumentsBundleCsv(filter);
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
          await api.downloadAuditLogCsv(filter);
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
        onValueChange={handleKindChange}
        options={TYPE_OPTIONS}
        disabled={disabled || busy}
        data-testid="select-report-download-type"
        className="min-w-[11rem]"
      />
      {flexiblePeriod && (
        <Select
          value={effectivePeriod}
          onValueChange={handlePeriodChange}
          options={PERIOD_OPTIONS}
          disabled={disabled || busy}
          data-testid="select-report-download-period"
          className="min-w-[8.5rem]"
        />
      )}
      {effectivePeriod === "range" && (
        <>
          <Input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            disabled={disabled || busy}
            className="h-8 w-[9.5rem]"
            data-testid="report-download-date-from"
            aria-label="From date"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            disabled={disabled || busy}
            className="h-8 w-[9.5rem]"
            data-testid="report-download-date-to"
            aria-label="To date"
          />
        </>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || busy || !month || rangeInvalid}
        data-testid="button-report-download"
        onClick={() => void handleDownload()}
        title={rangeInvalid ? "From date must be on or before to date" : undefined}
      >
        <Download className="h-4 w-4 mr-1" />
        {busy ? "Downloading…" : "Download"}
      </Button>
    </div>
  );
}
