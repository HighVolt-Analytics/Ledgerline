/** Document type class normalization — two coarse values only. */

export type DocumentTypeClass = "Transactional" | "Non-transactional";

export const KLASS_TRANSACTIONAL: DocumentTypeClass = "Transactional";
export const KLASS_NON_TRANSACTIONAL: DocumentTypeClass = "Non-transactional";

/** @deprecated Use KLASS_TRANSACTIONAL */
export const KLASS_TRANS_POSTING = KLASS_TRANSACTIONAL;
/** @deprecated Use KLASS_NON_TRANSACTIONAL */
export const KLASS_NON_TRANS_NON_POSTING = KLASS_NON_TRANSACTIONAL;

const LEGACY_TRANSACTIONAL = new Set([
  "transactional",
  "pre-transactional",
  "trans-posting",
  "trans posting",
]);
const LEGACY_NON_TRANSACTIONAL = new Set([
  "non-transactional",
  "non-trans, non-posting",
  "non-trans-non-posting",
  "supporting",
  "reconciliation",
  "informational",
  "master-data",
  "non-actionable",
  "compliance",
]);

export const DOCUMENT_TYPE_CLASSES: Array<"all" | DocumentTypeClass> = [
  "all",
  KLASS_TRANSACTIONAL,
  KLASS_NON_TRANSACTIONAL,
];

export function normalizeDocumentTypeKlass(raw: string | null | undefined): DocumentTypeClass {
  const token = (raw ?? "").trim().toLowerCase();
  if (LEGACY_TRANSACTIONAL.has(token)) return KLASS_TRANSACTIONAL;
  if (LEGACY_NON_TRANSACTIONAL.has(token)) return KLASS_NON_TRANSACTIONAL;
  return KLASS_NON_TRANSACTIONAL;
}

type KlassPostingSource = {
  klass?: string | null;
  posting?: string | null;
  playbookProfile?: string | null;
};

export function isTransPosting(defn: KlassPostingSource): boolean {
  return normalizeDocumentTypeKlass(defn.klass) === KLASS_TRANSACTIONAL;
}

export function derivePostingFromKlassAndProfile(
  klass: string | null | undefined,
  playbookProfile: string | null | undefined,
  existingPosting?: string | null
): string {
  const normalizedKlass = normalizeDocumentTypeKlass(klass);
  if (normalizedKlass === KLASS_NON_TRANSACTIONAL) return "No";
  const profile = (playbookProfile ?? "").trim().toLowerCase();
  if (profile === "pre_transactional") return "Down-payment";
  const existing = (existingPosting ?? "").trim();
  if (existing.toLowerCase() === "conditional") return "Conditional";
  return "Yes";
}

export function normalizeDocumentTypeIdentity(defn: KlassPostingSource): {
  klass: DocumentTypeClass;
  posting: string;
} {
  const klass = normalizeDocumentTypeKlass(defn.klass);
  const posting = derivePostingFromKlassAndProfile(
    klass,
    defn.playbookProfile,
    defn.posting
  );
  return { klass, posting };
}
