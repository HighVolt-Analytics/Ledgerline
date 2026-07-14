/**
 * Sync classifier tree from recognition mode (signals vs prompt).
 */

import {
  buildClassifierFromSignals,
  inferClassifierLayout,
  parseSignalsFromClassifier,
  type ClassifierLayout,
  type RecognitionSignalId,
} from "@/lib/documentClassifierBuilder";
import { templateSignalMetaForCode } from "@/lib/documentTypeTemplateMeta";
import {
  hasCompilableMatchRules,
  parseClassifierToMatchRules,
} from "@/lib/documentMatchRules";
import { allowedRecognitionSignalIds } from "@/lib/documentUserRecognition";
import type { DocumentTypeDefinition, RecognitionMode } from "@/lib/v5DocumentTypes";

function classifierLayoutForDraft(draft: DocumentTypeDefinition): ClassifierLayout {
  const matrixCode = (draft.matrixTemplateCode ?? "").trim().toUpperCase();
  if (matrixCode) {
    const meta = templateSignalMetaForCode(matrixCode);
    if (meta?.classifierLayout) {
      return meta.classifierLayout;
    }
  }
  return inferClassifierLayout(draft.classifier.root);
}

/** Recover recognitionSignals / mode from a stored classifier tree (legacy configs). */
export function hydrateRecognitionFromClassifier(
  draft: DocumentTypeDefinition
): DocumentTypeDefinition {
  const storedMode = String(draft.recognitionMode ?? "")
    .trim()
    .toLowerCase();
  const hasPrompt = (draft.llmPrompt ?? "").trim().length > 0;

  if (storedMode === "prompt" && hasPrompt) {
    return syncClassifierFromRecognition({
      ...draft,
      recognitionMode: "prompt",
      recognitionSignals: [],
      llmPrompt: draft.llmPrompt,
    });
  }

  const allowed = allowedRecognitionSignalIds();
  let signals = [...(draft.recognitionSignals ?? [])] as RecognitionSignalId[];
  if (signals.length === 0 && draft.classifier.enabled) {
    signals = parseSignalsFromClassifier(draft.classifier.root, allowed);
  }

  let recognitionMode: RecognitionMode =
    storedMode === "signals" || storedMode === "prompt" ? storedMode : "signals";
  const hasClassifierChildren = (draft.classifier.root.children?.length ?? 0) > 0;

  if (recognitionMode !== "prompt") {
    if (signals.length > 0 || (draft.classifier.enabled && hasClassifierChildren)) {
      recognitionMode = "signals";
    } else if (hasPrompt) {
      recognitionMode = "prompt";
    }
  }

  const hydrated: DocumentTypeDefinition = {
    ...draft,
    recognitionMode,
    recognitionSignals: recognitionMode === "signals" ? signals : [],
    llmPrompt: recognitionMode === "prompt" ? draft.llmPrompt : "",
  };

  if (recognitionMode === "signals" && signals.length > 0) {
    return syncClassifierFromRecognition(hydrated);
  }
  if (recognitionMode === "signals" && draft.classifier.enabled && hasClassifierChildren) {
    return hydrated;
  }
  return syncClassifierFromRecognition(hydrated);
}

export function syncClassifierFromRecognition(
  draft: DocumentTypeDefinition,
  layout?: ClassifierLayout
): DocumentTypeDefinition {
  if (draft.recognitionMode === "prompt") {
    return {
      ...draft,
      recognitionSignals: [],
      classifier: {
        ...draft.classifier,
        enabled: false,
        root: { type: "group", operator: "AND", children: [] },
      },
    };
  }

  const signals = (draft.recognitionSignals ?? []) as RecognitionSignalId[];
  if (signals.length === 0) {
    const hasClassifierChildren = (draft.classifier.root.children?.length ?? 0) > 0;
    if (draft.classifier.enabled && hasClassifierChildren) {
      return {
        ...draft,
        llmPrompt: "",
      };
    }
  }

  const compiled = buildClassifierFromSignals(
    signals,
    layout ?? classifierLayoutForDraft(draft),
    {
      priority: draft.classifier.priority || 100,
      confidence: draft.classifier.confidence ?? 0.85,
      enabled: signals.length > 0,
    }
  );
  return {
    ...draft,
    llmPrompt: "",
    classifier: compiled,
  };
}

export function applyRecognitionMode(
  draft: DocumentTypeDefinition,
  mode: RecognitionMode
): DocumentTypeDefinition {
  return syncClassifierFromRecognition({ ...draft, recognitionMode: mode });
}

export function applyRecognitionSignalIds(
  draft: DocumentTypeDefinition,
  signalIds: RecognitionSignalId[]
): DocumentTypeDefinition {
  return syncClassifierFromRecognition({
    ...draft,
    recognitionMode: "signals",
    recognitionSignals: signalIds,
  });
}

export function applyLlmPrompt(draft: DocumentTypeDefinition, prompt: string): DocumentTypeDefinition {
  return syncClassifierFromRecognition({
    ...draft,
    recognitionMode: "prompt",
    llmPrompt: prompt,
  });
}

export function recognitionSummary(draft: DocumentTypeDefinition): string {
  if (draft.recognitionMode === "prompt") {
    const line = draft.llmPrompt.trim().split("\n")[0]?.trim();
    return line || draft.title;
  }
  const form = parseClassifierToMatchRules(draft.classifier.root).form;
  if (hasCompilableMatchRules(form)) {
    const ruleCount =
      form.matchRules.filter((r) => r.field.trim()).length +
      form.excludeRules.filter((r) => r.field.trim()).length;
    if (ruleCount === 1) return "1 match rule";
    if (ruleCount > 1) return `${ruleCount} match rules`;
  }
  const count = draft.recognitionSignals?.length ?? 0;
  if (count === 1) return "1 recognition signal";
  if (count > 1) return `${count} recognition signals`;
  return draft.title;
}
