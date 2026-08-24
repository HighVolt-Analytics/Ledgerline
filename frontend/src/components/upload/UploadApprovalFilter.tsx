import { cn } from "@/lib/cn";
import {
  UPLOAD_APPROVAL_FILTERS,
  type UploadApprovalBoardCounts,
  type UploadApprovalFilterKey,
  type UploadApprovalStatusKey,
} from "@/lib/uploadApprovalFilter";

export function UploadApprovalFilter({
  value,
  onChange,
  counts,
}: {
  value: UploadApprovalStatusKey[];
  onChange: (value: UploadApprovalStatusKey[]) => void;
  counts: UploadApprovalBoardCounts;
}) {
  const allSelected = value.length === 0;

  function isItemSelected(key: UploadApprovalFilterKey) {
    return key === "all" ? allSelected : value.includes(key);
  }

  function selectItem(key: UploadApprovalFilterKey) {
    if (key === "all") {
      onChange([]);
      return;
    }
    onChange([key]);
  }

  return (
    <div
      className="upload-approval-filter"
      role="tablist"
      aria-label="Approval status"
      data-testid="button-upload-approval-filter"
    >
      {UPLOAD_APPROVAL_FILTERS.map((item) => {
        const isSelected = isItemSelected(item.key);
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={isSelected}
            data-testid={`upload-approval-filter-${item.key}`}
            className={cn(
              "upload-approval-filter__tab",
              `upload-approval-filter__tab--${item.key}`,
              isSelected && "upload-approval-filter__tab--active"
            )}
            onClick={() => selectItem(item.key)}
          >
            <span className="upload-approval-filter__dot" aria-hidden />
            <span className="upload-approval-filter__label">{item.label}</span>
            <span className="upload-approval-filter__count tnum">{counts[item.key]}</span>
          </button>
        );
      })}
    </div>
  );
}
