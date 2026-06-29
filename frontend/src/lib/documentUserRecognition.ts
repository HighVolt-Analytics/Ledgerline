/**
 * User-defined document type recognition modes (AI, signals, rules).
 */

import {
  buildClassifierFromSignals,
  parseSignalsFromClassifier,
  type RecognitionSignalId,
} from "@/lib/documentClassifierBuilder";
import { allRecognitionSignalOptions } from "@/lib/documentTypeTemplateMeta";
import {
  allRecognitionSignalIds,
  getRecognitionSignalCatalog,
} from "@/lib/recognitionSignalCatalog";
import {
  compileMatchRulesToClassifier,
  defaultMatchRulesForm,
  hasActionableMatchRules,
  parseClassifierToMatchRules,
} from "@/lib/documentMatchRules";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type UserRecognitionMode = "ai" | "signals" | "rules";

export const USER_RECOGNITION_MODES: Array<{
  id: UserRecognitionMode;
  label: string;
  hint: string;
}> = [
  {
    id: "rules",
    label: "Match / exclude rules",
    hint: "Strict AND/OR rules on headings, OCR text, and field presence.",
  },
  {
    id: "signals",
    label: "Document signals",
    hint: "Tick common patterns (invoice, PO, quote, bank letter, etc.) that appear on this document.",
  },
  {
    id: "ai",
    label: "AI description",
    hint: "Optional — LLM picks from your description when rules are not used.",
  },
];

export function starterMatchRulesForm() {
  return defaultMatchRulesForm();
}

/** Custom / user-defined types default to strict match rules (no AI description). */
export function initializeCustomDocumentTypeRecognition(
  draft: DocumentTypeDefinition
): DocumentTypeDefinition {
  const form = starterMatchRulesForm();
  return {
    ...draft,
    enabled: true,
    classifierCustomized: false,
    classifier: {
      ...draft.classifier,
      enabled: true,
      priority: draft.classifier.priority || 100,
      confidence: draft.classifier.confidence || 0.85,
      root: compileMatchRulesToClassifier(form),
    },
  };
}

export function recognitionSignalChoices(): Array<{
  id: RecognitionSignalId;
  label: string;
  hint: string;
  channel: string;
}> {
  const catalog = getRecognitionSignalCatalog();
  if (catalog) {
    return catalog.signals.map((row) => ({
      id: row.id,
      label: row.label,
      hint: row.hint,
      channel: row.channel || "General",
    }));
  }
  return allRecognitionSignalOptions().map((row) => ({
    ...row,
    channel: "General",
  }));
}

export function allowedRecognitionSignalIds(): RecognitionSignalId[] {
  const catalogIds = allRecognitionSignalIds(getRecognitionSignalCatalog());
  if (catalogIds.length > 0) return catalogIds;
  return allRecognitionSignalOptions().map((row) => row.id);
}

export function inferUserRecognitionMode(
  draft: Pick<DocumentTypeDefinition, "classifier">
): UserRecognitionMode {
  const { form } = parseClassifierToMatchRules(draft.classifier.root);
  if (hasActionableMatchRules(form)) return "rules";

  const allowed = allowedRecognitionSignalIds();
  const signals = parseSignalsFromClassifier(draft.classifier.root, allowed);
  if (signals.length > 0) return "signals";

  if (draft.classifier.enabled) return "rules";

  return "ai";
}

export function selectedRecognitionSignals(
  draft: Pick<DocumentTypeDefinition, "classifier">
): RecognitionSignalId[] {
  return parseSignalsFromClassifier(
    draft.classifier.root,
    allowedRecognitionSignalIds()
  );
}

export function hasRecognitionSignals(
  draft: Pick<DocumentTypeDefinition, "classifier">
): boolean {
  return selectedRecognitionSignals(draft).length > 0;
}

export function applyUserRecognitionMode(
  draft: DocumentTypeDefinition,
  mode: UserRecognitionMode
): DocumentTypeDefinition {
  if (mode === "ai") {
    return {
      ...draft,
      classifierCustomized: false,
      enabled: draft.enabled || false,
      classifier: {
        ...draft.classifier,
        enabled: false,
        root: { type: "group", operator: "AND", children: [] },
      },
    };
  }

  if (mode === "signals") {
    const existing = selectedRecognitionSignals(draft);
    const nextIds = existing.length > 0 ? existing : [];
    return {
      ...draft,
      classifierCustomized: false,
      enabled: true,
      classifier: buildClassifierFromSignals(nextIds, "grouped", {
        priority: draft.classifier.priority,
        confidence: draft.classifier.confidence,
        enabled: true,
      }),
    };
  }

  const form = starterMatchRulesForm();
  return {
    ...draft,
    classifierCustomized: false,
    enabled: true,
    classifier: {
      ...draft.classifier,
      enabled: true,
      root: compileMatchRulesToClassifier(form),
    },
  };
}

export function applyRecognitionSignals(
  draft: DocumentTypeDefinition,
  signalIds: RecognitionSignalId[]
): DocumentTypeDefinition {
  return {
    ...draft,
    classifierCustomized: false,
    enabled: true,
    classifier: buildClassifierFromSignals(signalIds, "grouped", {
      priority: draft.classifier.priority,
      confidence: draft.classifier.confidence,
      enabled: true,
    }),
  };
}
