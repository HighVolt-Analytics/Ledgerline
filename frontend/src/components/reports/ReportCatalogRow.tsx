import { Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import type { ReportCatalogItem, ReportExportFormat } from "@/api/types";
import { cn } from "@/lib/cn";

const DOWNLOAD_OPTIONS = [
  { value: "pdf", label: "PDF" },
  { value: "xlsx", label: "Excel (.xlsx)" },
];

type ReportCatalogRowProps = {
  report: ReportCatalogItem;
  favourite: boolean;
  expanded: boolean;
  onToggleFavourite: () => void;
  onTogglePreview: () => void;
  onDownloadFormat: (format: ReportExportFormat) => void;
  children?: React.ReactNode;
};

export function ReportCatalogRow({
  report,
  favourite,
  expanded,
  onToggleFavourite,
  onTogglePreview,
  onDownloadFormat,
  children,
}: ReportCatalogRowProps) {
  const panelId = `report-preview-${report.id}`;
  return (
    <div className="border-b border-border/60 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{report.name}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{report.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-11 w-11"
            aria-label={favourite ? `Unfavourite ${report.name}` : `Favourite ${report.name}`}
            aria-pressed={favourite}
            data-testid={`button-favourite-${report.id}`}
            onClick={onToggleFavourite}
          >
            <Star
              className={cn(favourite && "fill-current")}
              aria-hidden
            />
          </Button>
          <Button
            type="button"
            variant={expanded ? "default" : "outline"}
            className="min-h-11"
            aria-expanded={expanded}
            aria-controls={panelId}
            data-testid={`button-preview-${report.id}`}
            onClick={onTogglePreview}
          >
            Preview
          </Button>
          <div role="group" aria-label={`Download ${report.name}`}>
            <Select
              value=""
              placeholder="Download"
              options={DOWNLOAD_OPTIONS}
              onValueChange={(value) => onDownloadFormat(value as ReportExportFormat)}
              data-testid={`select-download-${report.id}`}
              className="min-h-11 min-w-[8rem]"
            />
          </div>
        </div>
      </div>
      {expanded ? (
        <div
          id={panelId}
          role="region"
          aria-label={`${report.name} preview`}
          className="mt-3"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
