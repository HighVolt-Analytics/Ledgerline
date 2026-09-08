export type MobileQuickActionPhotoMode = "compulsory" | "optional" | "none";

export type MobileQuickActionFieldConfig = {
  visible: boolean;
  required: boolean;
};

export type MobileQuickActionFieldsConfig = {
  expenseType: MobileQuickActionFieldConfig;
  adjustAdvance: MobileQuickActionFieldConfig;
  amount: MobileQuickActionFieldConfig;
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
    expenseType: { visible: true, required: true },
    adjustAdvance: { visible: true, required: false },
    amount: { visible: true, required: true },
    spentFor: { visible: true, required: true },
    remarks: { visible: true, required: false },
  };
}

export function newMobileQuickActionItem(
  documentTypeCode: string,
  label = ""
): MobileQuickActionItem {
  return {
    id: `mqa_${Math.random().toString(36).slice(2, 10)}`,
    documentTypeCode: documentTypeCode.trim().toUpperCase(),
    label: label.trim(),
    enabled: true,
    allowWithDoc: true,
    allowWithoutDoc: true,
    photoRequired: "optional",
    fields: defaultMobileQaFields(),
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
    const pick = (
      camel: keyof MobileQuickActionFieldsConfig,
      snake: string,
      fallback: MobileQuickActionFieldConfig
    ): MobileQuickActionFieldConfig => {
      const src = (fieldsRaw[camel] || fieldsRaw[snake] || {}) as Record<string, unknown>;
      return {
        visible: src.visible !== undefined ? Boolean(src.visible) : fallback.visible,
        required: src.required !== undefined ? Boolean(src.required) : fallback.required,
      };
    };
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
          : "optional",
      fields: {
        expenseType: pick("expenseType", "expense_type", base.fields.expenseType),
        adjustAdvance: pick("adjustAdvance", "adjust_advance", base.fields.adjustAdvance),
        amount: pick("amount", "amount", base.fields.amount),
        spentFor: pick("spentFor", "spent_for", base.fields.spentFor),
        remarks: pick("remarks", "remarks", base.fields.remarks),
      },
    });
    if (items.length >= 12) break;
  }
  return { items };
}
