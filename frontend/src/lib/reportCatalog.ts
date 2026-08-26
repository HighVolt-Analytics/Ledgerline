import { matchesListSearch } from "@/lib/listSearch";
import type { ReportCatalogItem, ReportCategory } from "@/api/types";

export const REPORT_CATEGORY_ORDER: ReportCategory[] = [
  "payables_receivables",
  "budgets_performance",
  "transactions",
  "exceptions_controls",
];

export const REPORT_CATEGORY_LABELS: Record<ReportCategory, string> = {
  payables_receivables: "Payables & Receivables",
  budgets_performance: "Budgets & Performance",
  transactions: "Transactions",
  exceptions_controls: "Exceptions & Controls",
};

export type ReportCategoryTab = "all" | ReportCategory;

export function filterCatalogItems(
  items: ReportCatalogItem[],
  search: string,
  category: ReportCategoryTab
): ReportCatalogItem[] {
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    return matchesListSearch(search, item.name, item.description, item.id);
  });
}

export function groupCatalogByCategory(
  items: ReportCatalogItem[]
): { category: ReportCategory; label: string; items: ReportCatalogItem[] }[] {
  return REPORT_CATEGORY_ORDER.map((category) => ({
    category,
    label: REPORT_CATEGORY_LABELS[category],
    items: items.filter((item) => item.category === category),
  })).filter((group) => group.items.length > 0);
}

export function favouriteItems(
  items: ReportCatalogItem[],
  favouriteIds: string[]
): ReportCatalogItem[] {
  const wanted = new Set(favouriteIds);
  return items.filter((item) => wanted.has(item.id));
}
