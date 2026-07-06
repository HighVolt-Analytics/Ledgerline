/**
 * Recognition signal catalogue helpers for the Rule Book editor.
 */

import type { RecognitionSignalId } from "@/lib/documentClassifierBuilder";
import { allRecognitionSignalOptions } from "@/lib/documentTypeTemplateMeta";
import {
  allRecognitionSignalIds,
  getRecognitionSignalCatalog,
} from "@/lib/recognitionSignalCatalog";
import { syncClassifierFromRecognition } from "@/lib/documentTypeRecognition";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

/** Custom / user-defined types default to signals mode with empty selection. */
export function initializeCustomDocumentTypeRecognition(
  draft: DocumentTypeDefinition
): DocumentTypeDefinition {
  return syncClassifierFromRecognition({
    ...draft,
    enabled: true,
    recognitionMode: "signals",
    recognitionSignals: [],
    llmPrompt: "",
  });
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

export function selectedRecognitionSignals(
  draft: Pick<DocumentTypeDefinition, "recognitionSignals">
): RecognitionSignalId[] {
  return [...(draft.recognitionSignals ?? [])] as RecognitionSignalId[];
}

export function hasRecognitionSignals(
  draft: Pick<DocumentTypeDefinition, "recognitionSignals">
): boolean {
  return selectedRecognitionSignals(draft).length > 0;
}
