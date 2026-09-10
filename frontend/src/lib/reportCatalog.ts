import { matchesListSearch } from "@/lib/listSearch";
import type { ReportCatalogItem, ReportCategory } from "@/api/types";

/** Compact catalog panels — original four sections. */
export const REPORT_CATEGORY_ORDER: ReportCategory[] = [
  "payables_receivables",
  "budgets_performance",
  "transactions",
  "exceptions_controls",
];

export const REPORT_CATEGORY_LABELS: Record<ReportCategory, string> = {
  payables_receivables: "Payables & receivables",
  budgets_performance: "Budgets & performance",
  transactions: "Transactions",
  exceptions_controls: "Exceptions & controls",
};

export const REPORT_CATEGORY_ACCENTS: Record<ReportCategory, string> = {
  payables_receivables: "#33C7A5",
  budgets_performance: "#7C93EF",
  transactions: "#4FB6D9",
  exceptions_controls: "#F2A154",
};

export type ReportCategoryTab = "all" | ReportCategory;

/**
 * Invoice Exception appears under payables and exceptions
 * (matches reports-redesign-compact.html dual-category row).
 */
export function reportCategories(item: ReportCatalogItem): ReportCategory[] {
  if (item.id === "invoice-exception") {
    return ["payables_receivables", "exceptions_controls"];
  }
  return [item.category];
}

/** Amber flag on Invoice Exception. */
export function isFlaggedReport(item: ReportCatalogItem): boolean {
  return item.id === "invoice-exception";
}

export function filterCatalogItems(
  items: ReportCatalogItem[],
  search: string,
  category: ReportCategoryTab
): ReportCatalogItem[] {
  return items.filter((item) => {
    if (category !== "all" && !reportCategories(item).includes(category)) return false;
    return matchesListSearch(search, item.name, item.description, item.id);
  });
}

export function groupCatalogByCategory(
  items: ReportCatalogItem[]
): { category: ReportCategory; label: string; items: ReportCatalogItem[] }[] {
  return REPORT_CATEGORY_ORDER.map((category) => ({
    category,
    label: REPORT_CATEGORY_LABELS[category],
    items: items.filter((item) => reportCategories(item).includes(category)),
  })).filter((group) => group.items.length > 0);
}

export function favouriteItems(
  items: ReportCatalogItem[],
  favouriteIds: string[]
): ReportCatalogItem[] {
  const wanted = new Set(favouriteIds);
  return items.filter((item) => wanted.has(item.id));
}
