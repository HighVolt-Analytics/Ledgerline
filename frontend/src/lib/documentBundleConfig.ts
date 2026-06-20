/** Bundle mandatory / conditional DT code helpers — align with backend playbook service. */

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

const DT_CODE_PATTERN = /^DT-\d{2}$/i;

export type PurchaseBundleRole = "" | "po" | "grn";

export const PURCHASE_BUNDLE_ROLE_OPTIONS: Array<{ value: PurchaseBundleRole; label: string }> = [
  { value: "", label: "None — match classified document on PO" },
  { value: "po", label: "PO — purchase order register or PO upload" },
  { value: "grn", label: "GRN — goods receipt register or GRN upload" },
];

export function isDtCode(value: string): boolean {
  return DT_CODE_PATTERN.test(value.trim());
}

export function normalizeDtCode(value: string): string | null {
  const trimmed = value.trim().toUpperCase();
  return isDtCode(trimmed) ? trimmed : null;
}

export function normalizeDtCodeList(values: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values ?? []) {
    const code = normalizeDtCode(raw);
    if (!code || seen.has(code)) continue;
    seen.add(code);
    out.push(code);
  }
  return out;
}

export function splitBundleItems(items: string[]): { dtCodes: string[]; advisories: string[] } {
  const dtCodes: string[] = [];
  const advisories: string[] = [];
  for (const raw of items) {
    const token = raw.trim();
    if (!token) continue;
    const code = normalizeDtCode(token);
    if (code) {
      if (!dtCodes.includes(code)) dtCodes.push(code);
    } else {
      advisories.push(token);
    }
  }
  return { dtCodes, advisories };
}

export function mergeBundleItems(dtCodes: string[], advisories: string[]): string[] {
  return [...normalizeDtCodeList(dtCodes), ...advisories.map((line) => line.trim()).filter(Boolean)];
}

export function documentTypeLabel(
  documentTypes: Array<{ code: string; shortTitle: string; title: string }>,
  code: string
): string {
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase());
  if (!row) return code;
  return `${row.code} · ${row.shortTitle || row.title}`;
}

export function purchaseBundleRoleLabel(role: PurchaseBundleRole | string | undefined): string | null {
  const token = (role || "").trim().toLowerCase() as PurchaseBundleRole;
  const row = PURCHASE_BUNDLE_ROLE_OPTIONS.find((option) => option.value === token);
  return row && row.value ? row.label : null;
}

export function bundleMemberDetailLabel(
  code: string,
  documentTypes: DocumentTypeDefinition[]
): string {
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase());
  const base = documentTypeLabel(documentTypes, code);
  if (!row?.purchaseBundleRole) return base;
  const roleHint =
    row.purchaseBundleRole === "po"
      ? "PO register / upload"
      : row.purchaseBundleRole === "grn"
        ? "GRN register / upload"
        : null;
  return roleHint ? `${base} (${roleHint})` : base;
}
