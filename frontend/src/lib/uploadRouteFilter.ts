import {
  ROUTE_EXPENSES,
  ROUTE_PURCHASE,
  ROUTE_SALES,
  ROUTE_TEAM,
} from "@/lib/invoice";

/** Upload list filters — exact Invoice.route_target values, not operations pages. */
export const UPLOAD_ROUTE_FILTERS = [
  {
    value: "team-expenses",
    label: "Team Expenses",
    routeTarget: ROUTE_TEAM,
    moduleKey: "team_expenses",
    testid: "tab-upload-team-expenses",
  },
  {
    value: "expenses",
    label: "Expenses Management",
    routeTarget: ROUTE_EXPENSES,
    moduleKey: "expenses",
    testid: "tab-upload-expenses",
  },
  {
    value: "purchases",
    label: "Purchase Management",
    routeTarget: ROUTE_PURCHASE,
    moduleKey: "purchase",
    testid: "tab-upload-purchases",
  },
  {
    value: "sales",
    label: "Sales Management",
    routeTarget: ROUTE_SALES,
    moduleKey: "sales",
    testid: "tab-upload-sales",
  },
] as const;

export type UploadRouteFilterValue = (typeof UPLOAD_ROUTE_FILTERS)[number]["value"];

export function isUploadRouteFilter(value: string | null): value is UploadRouteFilterValue {
  return UPLOAD_ROUTE_FILTERS.some((tab) => tab.value === value);
}

export function parseUploadRouteFilter(value: string | null): UploadRouteFilterValue | null {
  return isUploadRouteFilter(value) ? value : null;
}

export function routeTargetForUploadFilter(value: UploadRouteFilterValue): string {
  const tab = UPLOAD_ROUTE_FILTERS.find((item) => item.value === value);
  return tab?.routeTarget ?? "";
}

export function uploadRouteFilterLabel(value: UploadRouteFilterValue): string {
  const tab = UPLOAD_ROUTE_FILTERS.find((item) => item.value === value);
  return tab?.label ?? value;
}
