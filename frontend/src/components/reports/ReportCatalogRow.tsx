import type { ReportCatalogItem, ReportExportFormat } from "@/api/types";
import { isFlaggedReport } from "@/lib/reportCatalog";
import { cn } from "@/lib/cn";

const STAR_OUTLINE = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26" />
  </svg>
);

const STAR_FILLED = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" aria-hidden>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26" />
  </svg>
);

const PREVIEW_SVG = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const DOWNLOAD_SVG = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
    <path d="M12 3v13" />
    <path d="M7 11l5 5 5-5" />
    <path d="M5 21h14" />
  </svg>
);

const INFO_SVG = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <circle cx="12" cy="12" r="9" />
    <line x1="12" y1="11" x2="12" y2="16" />
    <circle cx="12" cy="8" r="0.5" fill="currentColor" />
  </svg>
);

type ReportCatalogRowProps = {
  report: ReportCatalogItem;
  favourite: boolean;
  expanded: boolean;
  onToggleFavourite: () => void;
  onTogglePreview: () => void;
  onDownloadFormat: (format: ReportExportFormat) => void;
};

export function ReportCatalogRow({
  report,
  favourite,
  expanded,
  onToggleFavourite,
  onTogglePreview,
  onDownloadFormat,
}: ReportCatalogRowProps) {
  const panelId = `report-preview-${report.id}`;
  const flagged = isFlaggedReport(report);

  return (
    <div
      className={cn("rc-report-row", flagged && "exception", expanded && "is-expanded")}
    >
      <button
        type="button"
        className={cn("rc-star", favourite && "active")}
        aria-label={favourite ? `Unfavourite ${report.name}` : `Favourite ${report.name}`}
        aria-pressed={favourite}
        data-testid={`button-favourite-${report.id}`}
        onClick={onToggleFavourite}
      >
        {favourite ? STAR_FILLED : STAR_OUTLINE}
      </button>

      <span className="rc-report-name" title={report.name}>
        {report.name}
      </span>

      <div className="rc-row-actions">
        <button
          type="button"
          className={cn("rc-icon-btn", expanded && "is-active")}
          aria-label={`Preview ${report.name}`}
          aria-expanded={expanded}
          aria-controls={panelId}
          data-testid={`button-preview-${report.id}`}
          onClick={onTogglePreview}
        >
          {PREVIEW_SVG}
        </button>
        <button
          type="button"
          className="rc-icon-btn"
          aria-label={`Download ${report.name}`}
          data-testid={`select-download-${report.id}`}
          onClick={() => onDownloadFormat("xlsx")}
        >
          {DOWNLOAD_SVG}
        </button>
        <div className="rc-info-wrap" tabIndex={0}>
          <button
            type="button"
            className="rc-info-btn"
            aria-label={`${report.name} details`}
          >
            {INFO_SVG}
          </button>
          <div className="rc-tooltip" role="tooltip">
            {report.description}
          </div>
        </div>
      </div>
    </div>
  );
}
