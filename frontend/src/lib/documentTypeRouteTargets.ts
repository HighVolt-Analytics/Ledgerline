/** Shipped route targets per DT code — align with backend document_type_catalog.py */

export const DOCUMENT_TYPE_ROUTE_TARGETS: Record<string, string> = {
  "DT-01": "Purchase Management",
  "DT-02": "Purchase Management",
  "DT-03": "Purchase Management",
  "DT-04": "Purchase Management",
  "DT-05": "Purchase Management",
  "DT-06": "Vault",
  "DT-07": "Purchase Management",
  "DT-08": "Expenses Management",
  "DT-09": "Purchase Management",
  "DT-10": "Purchase Management",
  "DT-11": "Purchase Management",
  "DT-12": "Team Expenses",
  "DT-13": "Vault",
  "DT-16": "Purchase Management",
  "DT-17": "Purchase Management",
  "DT-18": "Vault",
  "DT-19": "Purchase Management",
  "DT-20": "Purchase Management",
  "DT-21": "Expenses Management",
  "DT-22": "Vault",
  "DT-23": "Vault",
  "DT-24": "Vault",
  "DT-25": "Vault",
};

export function routeTargetForDocumentTypeCode(code: string): string {
  return DOCUMENT_TYPE_ROUTE_TARGETS[code.trim().toUpperCase()] ?? "Vault";
}
