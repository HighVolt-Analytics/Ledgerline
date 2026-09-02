import type { AllDocumentsChannelTab } from "@/lib/allDocumentsSummary";
import {
  UPLOAD_DOCUMENT_AREA_FILTERS,
  uploadApprovalFilterLabel,
  type UploadApprovalStatusKey,
  type UploadDocumentAreaKey,
} from "@/lib/uploadApprovalFilter";

export type UploadAnalysisViewTab = "summary" | "setup";

export type UploadAnalysisScope = {
  channel: AllDocumentsChannelTab;
  view: UploadAnalysisViewTab;
  documentAreas: UploadDocumentAreaKey[];
  approvalFilter: UploadApprovalStatusKey[];
  searchQuery: string;
};

const CHANNEL_LABELS: Record<AllDocumentsChannelTab, string> = {
  all: "All Documents",
  upload: "Upload",
  email: "Email",
  whatsapp: "WhatsApp",
  viber: "Viber",
  "bank-feeds": "Bank feeds",
};

export function uploadChannelLabel(channel: AllDocumentsChannelTab): string {
  return CHANNEL_LABELS[channel];
}

export function uploadAnalysisScopeTitle(scope: UploadAnalysisScope): string {
  return uploadChannelLabel(scope.channel);
}

export function uploadAnalysisScopeSubtitle(scope: UploadAnalysisScope): string {
  const parts: string[] = [];

  parts.push(scope.view === "setup" ? "Setup" : "Summary");

  if (scope.documentAreas.length === 0) {
    parts.push("All areas");
  } else {
    const labels = scope.documentAreas.map(
      (key) => UPLOAD_DOCUMENT_AREA_FILTERS.find((item) => item.key === key)?.label ?? key
    );
    parts.push(labels.join(", "));
  }

  if (scope.approvalFilter.length > 0) {
    parts.push(uploadApprovalFilterLabel(scope.approvalFilter));
  }

  if (scope.searchQuery.trim()) {
    parts.push(`Search: “${scope.searchQuery.trim()}”`);
  }

  return parts.join(" · ");
}

export function uploadAnalysisScopePills(scope: UploadAnalysisScope): string[] {
  const pills = [uploadChannelLabel(scope.channel), scope.view === "setup" ? "Setup" : "Summary"];

  if (scope.documentAreas.length === 0) {
    pills.push("All areas");
  } else {
    for (const key of scope.documentAreas) {
      const label = UPLOAD_DOCUMENT_AREA_FILTERS.find((item) => item.key === key)?.label;
      if (label) pills.push(label);
    }
  }

  if (scope.approvalFilter.length > 0) {
    pills.push(uploadApprovalFilterLabel(scope.approvalFilter));
  } else {
    pills.push("All statuses");
  }

  if (scope.searchQuery.trim()) {
    pills.push(`“${scope.searchQuery.trim()}”`);
  }

  return pills;
}

export function uploadAnalysisSections(scope: UploadAnalysisScope) {
  const documentScope =
    scope.view === "summary" && scope.channel !== "bank-feeds";

  return {
    showDocumentAnalysis: documentScope,
    showSetupNotice: scope.view === "setup",
    showBankFeedsNotice: scope.channel === "bank-feeds" && scope.view === "summary",
  };
}

export function primaryDocumentArea(
  areas: UploadDocumentAreaKey[]
): UploadDocumentAreaKey | null {
  return areas.length === 1 ? areas[0]! : null;
}

export const AREA_ANALYSIS_LABEL: Record<UploadDocumentAreaKey, string> = {
  team: "Team Expenses",
  expenses: "Expenses Management",
  purchase: "Purchase Management",
  sales: "Sales Management",
};

export const CHANNEL_FUNNEL_LABEL: Record<AllDocumentsChannelTab, string> = {
  all: "FY26 YTD documents",
  upload: "Manual uploads YTD",
  email: "Email capture YTD",
  whatsapp: "WhatsApp claims YTD",
  viber: "Viber claims YTD",
  "bank-feeds": "Bank feed lines YTD",
};

export const STATUS_FILTER_SCALE: Record<UploadApprovalStatusKey, number> = {
  review: 0.34,
  processing: 0.22,
  approved: 0.52,
  rejected: 0.08,
};
