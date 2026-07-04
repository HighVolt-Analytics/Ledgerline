/** Default playbook profile per shipped DT code — align with backend playbook_profile_catalog.py */

import type { PlaybookProfile } from "@/lib/documentPlaybookConfig";

export const DEFAULT_PLAYBOOK_PROFILE_BY_CODE: Record<string, PlaybookProfile> = {
  "DT-01": "po_goods",
  "DT-02": "supporting",
  "DT-03": "supporting",
  "DT-04": "credit_adjustment",
  "DT-05": "debit_note",
  "DT-06": "pre_transactional",
  "DT-07": "standard_transactional",
  "DT-08": "direct_expense",
  "DT-09": "freight_logistics",
  "DT-10": "import_dossier",
  "DT-11": "intercompany",
  "DT-12": "employee_claim",
  "DT-13": "reconciliation",
  "DT-14": "supporting",
  "DT-15": "supporting",
  "DT-16": "supporting",
  "DT-17": "supporting",
  "DT-18": "supporting",
  "DT-19": "standard_transactional",
  "DT-20": "standard_transactional",
  "DT-21": "direct_expense",
  "DT-22": "informational",
  "DT-23": "master_data",
  "DT-24": "non_actionable",
  "DT-25": "compliance_route",
  "DT-26": "ar_goods",
  "DT-27": "supporting",
  "DT-28": "supporting",
};

export function defaultPlaybookProfileForCode(code: string): PlaybookProfile {
  return DEFAULT_PLAYBOOK_PROFILE_BY_CODE[code.trim().toUpperCase()] ?? "standard_transactional";
}
