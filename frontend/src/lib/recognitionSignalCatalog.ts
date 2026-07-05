/**
 * Recognition signal registry — loaded from GET /api/rule-book/recognition-signals.
 */

import type {
  DocumentRuleCondition,
} from "@/lib/v5DocumentTypes";

export type RecognitionSignalId = string;

export type RecognitionSignalCondition = {
  field: string;
  operator: DocumentRuleCondition["operator"];
  value: string;
};

export type RecognitionSignalEntry = {
  id: RecognitionSignalId;
  label: string;
  hint: string;
  channel: string;
  strength: string;
  example: string;
  condition: RecognitionSignalCondition;
};

export type RecognitionSignalCatalog = {
  weakSignalIds: RecognitionSignalId[];
  pickGroups: RecognitionSignalId[][];
  supportingGuards: DocumentRuleCondition[];
  signals: RecognitionSignalEntry[];
  playbookRecommendedIdentity: Record<string, RecognitionSignalId[]>;
};

let activeCatalog: RecognitionSignalCatalog | null = null;

export function setRecognitionSignalCatalog(catalog: RecognitionSignalCatalog): void {
  activeCatalog = catalog;
}

export function getRecognitionSignalCatalog(): RecognitionSignalCatalog | null {
  return activeCatalog;
}

export function clearRecognitionSignalCatalog(): void {
  activeCatalog = null;
}

export function recognitionSignalCatalogFromApi(raw: {
  weak_signal_ids: string[];
  pick_groups: string[][];
  supporting_guards: Array<Record<string, unknown>>;
  signals: Array<{
    id: string;
    label: string;
    hint: string;
    channel: string;
    strength: string;
    example: string;
    condition: { field: string; operator: string; value: string };
  }>;
  playbook_recommended_identity: Record<string, string[]>;
}): RecognitionSignalCatalog {
  return {
    weakSignalIds: raw.weak_signal_ids,
    pickGroups: raw.pick_groups,
    supportingGuards: raw.supporting_guards.map((row) => ({
      type: "condition",
      field: String(row.field ?? ""),
      operator: row.operator as DocumentRuleCondition["operator"],
      value: String(row.value ?? ""),
    })),
    signals: raw.signals.map((row) => ({
      id: row.id,
      label: row.label,
      hint: row.hint,
      channel: row.channel,
      strength: row.strength,
      example: row.example,
      condition: {
        field: row.condition.field,
        operator: row.condition.operator as DocumentRuleCondition["operator"],
        value: row.condition.value,
      },
    })),
    playbookRecommendedIdentity: raw.playbook_recommended_identity,
  };
}

export function allRecognitionSignalIds(catalog?: RecognitionSignalCatalog | null): RecognitionSignalId[] {
  const source = catalog ?? activeCatalog;
  if (!source) return [];
  return source.signals.map((row) => row.id);
}

export function recognitionSignalOptions(
  catalog?: RecognitionSignalCatalog | null
): Array<{ id: RecognitionSignalId; label: string; hint: string }> {
  const source = catalog ?? activeCatalog;
  if (!source) return [];
  return source.signals.map((row) => ({
    id: row.id,
    label: row.label,
    hint: row.hint,
  }));
}

export function signalConditionFromCatalog(
  signalId: RecognitionSignalId,
  catalog?: RecognitionSignalCatalog | null
): DocumentRuleCondition | null {
  const source = catalog ?? activeCatalog;
  const row = source?.signals.find((entry) => entry.id === signalId);
  if (!row) return null;
  return {
    type: "condition",
    field: row.condition.field,
    operator: row.condition.operator,
    value: row.condition.value,
  };
}

export function weakSignalSet(catalog?: RecognitionSignalCatalog | null): Set<RecognitionSignalId> {
  const source = catalog ?? activeCatalog;
  return new Set(source?.weakSignalIds ?? []);
}

export function pickGroups(catalog?: RecognitionSignalCatalog | null): RecognitionSignalId[][] {
  const source = catalog ?? activeCatalog;
  return source?.pickGroups ?? [];
}

export function supportingGuardConditions(
  catalog?: RecognitionSignalCatalog | null
): DocumentRuleCondition[] {
  const source = catalog ?? activeCatalog;
  return source?.supportingGuards ?? [];
}

export function isKnownRecognitionSignal(
  signalId: string,
  catalog?: RecognitionSignalCatalog | null
): boolean {
  const source = catalog ?? activeCatalog;
  return Boolean(source?.signals.some((row) => row.id === signalId));
}
