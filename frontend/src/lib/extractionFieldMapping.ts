/**
 * Dictionary extraction-field mapping (Tier 1 confirmed + Tier 2 draft).
 * Tier 2 aliases remap to catalogue keys; unmapped draft keys stay hints-only.
 *
 * Direction-sensitive draft keys (AP/vendor vs AR/customer) must not use a single
 * global target — same failure mode as the original tax_id → seller_tax_id bug:
 *   - tax_id        → seller_tax_id | buyer_tax_id
 *   - bank_details  → bank_details (vendor pay-to) | buyer_bank_details
 * Other kept/remapped Tier 2 keys are direction-neutral (dates, cost_centre,
 * service_period, remittance_reference, …) or already party-named (customer →
 * buyer_name only appears on customer-side entries).
 */

import mappingFile from "@/lib/extraction_field_mapping.json";
import {
  isPresetExtractionFieldKey,
  type ExtractionFieldKey,
} from "@/lib/documentExtractionFields";
import { DICTIONARY_ENTRIES } from "@/lib/documentTypeDictionary";

export type ExtractionFieldMappingEntry = {
  code: string;
  title: string;
  industry: string;
  candidateExtractionFields?: string[];
  candidateFieldsTier1Confirmed: string[];
  candidateFieldsTier2Draft: string[];
  unresolvedPhrases: string[];
};

export type ExtractionFieldMappingFile = {
  note?: string;
  tier1ConfirmedKeys?: string[];
  entries: ExtractionFieldMappingEntry[];
};

/**
 * Static Tier 2 remaps (identity + fixed aliases).
 * Direction-sensitive keys (`tax_id`, `bank_details`) resolve via helpers below.
 */
export const TIER2_FIELD_REMAP: Record<string, ExtractionFieldKey> = {
  cost_centre: "cost_centre",
  due_date: "due_date",
  invoice_date: "invoice_date",
  customer: "buyer_name",
  payment_reference: "remittance_reference",
  service_period: "service_period",
  claim_id: "claim_id",
  employee_id: "employee_id",
  advance_reference: "advance_reference",
  payment_method: "payment_method",
  contract_reference: "contract_reference",
  project_reference: "project_reference",
  credit_note_no: "credit_note_no",
  original_invoice_reference: "original_invoice_reference",
  receipt_date: "receipt_date",
  delivery_date: "delivery_date",
};

const MAPPING = mappingFile as ExtractionFieldMappingFile;

const BY_CODE = new Map(
  (MAPPING.entries ?? []).map((row) => [row.code.trim().toUpperCase(), row] as const)
);

const DICTIONARY_BY_CODE = new Map(
  DICTIONARY_ENTRIES.map((row) => [row.code.trim().toUpperCase(), row] as const)
);

export function getExtractionFieldMappingEntry(
  dictionaryCode: string | undefined | null
): ExtractionFieldMappingEntry | undefined {
  const code = (dictionaryCode ?? "").trim().toUpperCase();
  if (!code) return undefined;
  return BY_CODE.get(code);
}

function pushUnique(out: string[], seen: Set<string>, key: string): void {
  if (!key || seen.has(key)) return;
  if (!isPresetExtractionFieldKey(key)) return;
  seen.add(key);
  out.push(key);
}

/** True when the dictionary entry is AR / customer-side (not vendor pay-to). */
export function isCustomerSideDictionaryCode(
  dictionaryCode: string | undefined | null
): boolean {
  const entry = DICTIONARY_BY_CODE.get((dictionaryCode ?? "").trim().toUpperCase());
  if (!entry) return false;
  return entry.counterpartyType === "customer" || entry.routeTarget === "Sales Management";
}

/** Customer-side docs: tax_id is the customer's ID → buyer_tax_id. Otherwise supplier → seller_tax_id. */
export function remapTaxIdForDictionaryCode(
  dictionaryCode: string | undefined | null
): ExtractionFieldKey {
  return isCustomerSideDictionaryCode(dictionaryCode) ? "buyer_tax_id" : "seller_tax_id";
}

/**
 * Vendor/AP: pay-to bank on the invoice → bank_details (VR13 vendor match).
 * Customer/AR: counterparty bank → buyer_bank_details (not the vendor pay-to field).
 */
export function remapBankDetailsForDictionaryCode(
  dictionaryCode: string | undefined | null
): ExtractionFieldKey {
  return isCustomerSideDictionaryCode(dictionaryCode) ? "buyer_bank_details" : "bank_details";
}

export function remapTier2DraftKey(
  draftKey: string,
  dictionaryCode: string | undefined | null
): ExtractionFieldKey | null {
  const draft = draftKey.trim().toLowerCase();
  if (!draft) return null;
  if (draft === "tax_id") return remapTaxIdForDictionaryCode(dictionaryCode);
  if (draft === "bank_details") return remapBankDetailsForDictionaryCode(dictionaryCode);
  const staticRemap = TIER2_FIELD_REMAP[draft];
  if (staticRemap) return staticRemap;
  if (isPresetExtractionFieldKey(draft)) return draft as ExtractionFieldKey;
  return null;
}

/**
 * Resolve adopt-time extractionFields from mapping tiers.
 * Tier 1: merge as-is (must already be catalogue keys).
 * Tier 2: remap or keep only when target exists in catalogue; else drop.
 */
export function resolvedExtractionFieldsFromMapping(
  dictionaryCode: string | undefined | null
): string[] {
  const entry = getExtractionFieldMappingEntry(dictionaryCode);
  if (!entry) return [];
  const seen = new Set<string>();
  const out: string[] = [];

  for (const raw of entry.candidateFieldsTier1Confirmed ?? []) {
    const key = String(raw ?? "").trim().toLowerCase();
    pushUnique(out, seen, key);
  }

  for (const raw of entry.candidateFieldsTier2Draft ?? []) {
    const remapped = remapTier2DraftKey(String(raw ?? ""), dictionaryCode);
    if (remapped) pushUnique(out, seen, remapped);
  }

  return out;
}

/**
 * Hint text: unresolved phrases + Tier 2 drafts that were not merged into catalogue keys.
 */
export function unresolvedExtractionHintsFromMapping(
  dictionaryCode: string | undefined | null
): string[] {
  const entry = getExtractionFieldMappingEntry(dictionaryCode);
  if (!entry) return [];
  const hints: string[] = [];
  const seen = new Set<string>();

  for (const phrase of entry.unresolvedPhrases ?? []) {
    const token = String(phrase ?? "").trim();
    if (!token || seen.has(token)) continue;
    seen.add(token);
    hints.push(token);
  }

  for (const raw of entry.candidateFieldsTier2Draft ?? []) {
    const draft = String(raw ?? "").trim().toLowerCase();
    if (!draft) continue;
    const remapped = remapTier2DraftKey(draft, dictionaryCode);
    if (remapped && isPresetExtractionFieldKey(remapped)) continue;
    const label = `Draft field (not in catalogue): ${draft}`;
    if (seen.has(label)) continue;
    seen.add(label);
    hints.push(label);
  }

  return hints;
}
