import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  selectUploadDocumentArea,
  UPLOAD_APPROVAL_STATUS_FILTERS,
  UPLOAD_DOCUMENT_AREA_FILTERS,
  type UploadApprovalBoardCounts,
  type UploadApprovalStatusKey,
  type UploadDocumentAreaKey,
} from "@/lib/uploadApprovalFilter";

export function UploadTableFilterRail({
  area,
  onAreaChange,
  status,
  onStatusChange,
  counts,
  visibleAreas,
}: {
  area: UploadDocumentAreaKey[];
  onAreaChange: (value: UploadDocumentAreaKey[]) => void;
  status: UploadApprovalStatusKey[];
  onStatusChange: (value: UploadApprovalStatusKey[]) => void;
  counts: UploadApprovalBoardCounts;
  visibleAreas: UploadDocumentAreaKey[];
}) {
  const areas = UPLOAD_DOCUMENT_AREA_FILTERS.filter((item) => visibleAreas.includes(item.key));

  function selectStatus(key: UploadApprovalStatusKey) {
    if (status.length === 1 && status[0] === key) {
      onStatusChange([]);
      return;
    }
    onStatusChange([key]);
  }

  return (
    <div
      className="upload-table-filter-rail"
      data-testid="upload-table-filter-rail"
    >
      {areas.length > 0 ? (
        <div
          className="upload-table-filter-rail__group upload-table-filter-rail__group--area"
          role="group"
          aria-label="Document area"
        >
          {areas.map((item) => {
            const selected = area.includes(item.key);
            return (
              <button
                key={item.key}
                type="button"
                aria-pressed={selected}
                data-testid={`upload-area-filter-${item.key}`}
                className={cn(
                  "upload-table-filter-rail__area",
                  selected && "upload-table-filter-rail__area--active"
                )}
                onClick={() => onAreaChange(selectUploadDocumentArea(area, item.key))}
              >
                {selected ? (
                  <Check className="upload-table-filter-rail__area-check" aria-hidden />
                ) : null}
                {item.label}
              </button>
            );
          })}
        </div>
      ) : null}

      <div
        className="upload-table-filter-rail__group upload-table-filter-rail__group--status"
        role="group"
        aria-label="Workflow status"
        data-testid="button-upload-approval-filter"
      >
        {UPLOAD_APPROVAL_STATUS_FILTERS.map((item) => {
          const selected = status.includes(item.key);
          return (
            <button
              key={item.key}
              type="button"
              aria-pressed={selected}
              data-testid={`upload-approval-filter-${item.key}`}
              onClick={() => selectStatus(item.key)}
              className={cn(
                "upload-table-filter-rail__status",
                `upload-table-filter-rail__status--${item.key}`,
                selected && "upload-table-filter-rail__status--active"
              )}
            >
              <span className="upload-table-filter-rail__dot" aria-hidden />
              <span className="upload-table-filter-rail__status-label">{item.label}</span>
              <span className="upload-table-filter-rail__count tnum">{counts[item.key]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
