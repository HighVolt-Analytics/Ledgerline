import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type MobileQuickActionPhotoMode = "compulsory" | "optional" | "none";

export type MobileQuickActionFieldConfig = {
  visible: boolean;
  required: boolean;
};

/** Fixed Quick Action chrome fields. DT detail fields come from the document type itself. */
export type MobileQuickActionFieldsConfig = {
  parentLedger: MobileQuickActionFieldConfig;
  adjustAdvance: MobileQuickActionFieldConfig;
  spentFor: MobileQuickActionFieldConfig;
  remarks: MobileQuickActionFieldConfig;
};

export type MobileQuickActionItem = {
  id: string;
  documentTypeCode: string;
  label: string;
  enabled: boolean;
  allowWithDoc: boolean;
  allowWithoutDoc: boolean;
  photoRequired: MobileQuickActionPhotoMode;
  fields: MobileQuickActionFieldsConfig;
};

export type MobileQuickActionsSettings = {
  items: MobileQuickActionItem[];
};

export function defaultMobileQaFields(): MobileQuickActionFieldsConfig {
  return {
    parentLedger: { visible: true, required: true },
    adjustAdvance: { visible: true, required: false },
    spentFor: { visible: true, required: true },
    remarks: { visible: true, required: false },
  };
}

export function newMobileQuickActionItem(
  documentTypeCode: string,
  label = "",
  _dt?: DocumentTypeDefinition
): MobileQuickActionItem {
  return {
    id: `mqa_${Math.random().toString(36).slice(2, 10)}`,
    documentTypeCode: documentTypeCode.trim().toUpperCase(),
    label: label.trim(),
    enabled: true,
    allowWithDoc: true,
    allowWithoutDoc: true,
    photoRequired: "none",
    fields: defaultMobileQaFields(),
  };
}

function pickField(
  fieldsRaw: Record<string, unknown>,
  camel: string,
  snake: string,
  fallback: MobileQuickActionFieldConfig
): MobileQuickActionFieldConfig {
  const src = (fieldsRaw[camel] || fieldsRaw[snake] || {}) as Record<string, unknown>;
  return {
    visible: src.visible !== undefined ? Boolean(src.visible) : fallback.visible,
    required: src.required !== undefined ? Boolean(src.required) : fallback.required,
  };
}

export function normalizeMobileQuickActionsSettings(
  raw: unknown
): MobileQuickActionsSettings {
  if (!raw || typeof raw !== "object") return { items: [] };
  const o = raw as Record<string, unknown>;
  const itemsRaw = Array.isArray(o.items) ? o.items : [];
  const items: MobileQuickActionItem[] = [];
  const seenCodes = new Set<string>();
  for (const row of itemsRaw) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const code = String(r.documentTypeCode || r.document_type_code || "")
      .trim()
      .toUpperCase();
    if (!code || seenCodes.has(code)) continue;
    seenCodes.add(code);
    const base = newMobileQuickActionItem(code, String(r.label || ""));
    const fieldsRaw = (r.fields || {}) as Record<string, unknown>;
    const photo = String(r.photoRequired ?? r.photo_required ?? base.photoRequired);
    let allowWith =
      r.allowWithDoc !== undefined
        ? Boolean(r.allowWithDoc)
        : r.allow_with_doc !== undefined
          ? Boolean(r.allow_with_doc)
          : true;
    let allowWithout =
      r.allowWithoutDoc !== undefined
        ? Boolean(r.allowWithoutDoc)
        : r.allow_without_doc !== undefined
          ? Boolean(r.allow_without_doc)
          : true;
    if (!allowWith && !allowWithout) allowWith = true;

    // Legacy expenseType → parentLedger; amount / detailFields ignored (DT owns details).
    let parentLedger = pickField(
      fieldsRaw,
      "parentLedger",
      "parent_ledger",
      base.fields.parentLedger
    );
    if (
      fieldsRaw.parentLedger == null &&
      fieldsRaw.parent_ledger == null &&
      (fieldsRaw.expenseType != null || fieldsRaw.expense_type != null)
    ) {
      parentLedger = pickField(
        fieldsRaw,
        "expenseType",
        "expense_type",
        base.fields.parentLedger
      );
    }

    items.push({
      id: String(r.id || base.id),
      documentTypeCode: code,
      label: String(r.label || "").trim(),
      enabled: r.enabled === undefined ? true : Boolean(r.enabled),
      allowWithDoc: allowWith,
      allowWithoutDoc: allowWithout,
      photoRequired:
        photo === "compulsory" || photo === "optional" || photo === "none"
          ? photo
          : "none",
      fields: {
        parentLedger,
        adjustAdvance: pickField(
          fieldsRaw,
          "adjustAdvance",
          "adjust_advance",
          base.fields.adjustAdvance
        ),
        spentFor: pickField(fieldsRaw, "spentFor", "spent_for", base.fields.spentFor),
        remarks: pickField(fieldsRaw, "remarks", "remarks", base.fields.remarks),
      },
    });
    if (items.length >= 12) break;
  }
  return { items };
}
