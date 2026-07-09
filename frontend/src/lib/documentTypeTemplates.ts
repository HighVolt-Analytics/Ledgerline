/**
 * User-facing document type templates for the Rule Book catalogue.
 * Built from the shipped Excel / v5 matrix (v5DocumentTypes.json).
 */

import shippedCatalog from "@/lib/v5DocumentTypes.json";
import shippedDefaults from "@/lib/documentTypeDefaults.json";
import classifierPresets from "@/lib/documentTypeClassifierPresets.json";
import { playbookPresetForProfile, type PlaybookProfile } from "@/lib/documentPlaybookConfig";
import type {
  DocumentTypeClassifier,
  DocumentTypeDefinition,
} from "@/lib/v5DocumentTypes";
import { createBlankDocumentType, emptyDocumentTypePostTo, nextOrgDocumentTypeCode } from "@/lib/v5DocumentTypes";
import type { DocumentTypeClass } from "@/lib/documentTypeKlass";
import type { PurchaseBundleRole, SalesBundleRole } from "@/lib/documentBundleConfig";
import { routeTargetForDocumentTypeCode } from "@/lib/documentTypeRouteTargets";
import { defaultPlaybookProfileForCode } from "@/lib/documentTypePlaybookDefaults";
import {
  templateSignalMetaForCode,
  type RecognitionSignalOption,
  type RouteConfidencePreset,
  type ClassifierLayout,
  type RecognitionSignalId,
} from "@/lib/documentTypeTemplateMeta";
import {
  buildClassifierFromSignals,
  inferClassifierLayout,
  parseSignalsFromClassifier,
} from "@/lib/documentClassifierBuilder";
import {
  absentFieldsFromExcludeRules,
  compileMatchRulesToClassifier,
} from "@/lib/documentMatchRules";
import { normalizeBundleConditional } from "@/lib/documentBundleConfig";
import {
  defaultCompulsoryForTemplate,
} from "@/lib/documentCompulsoryFields";
import {
  isTransactionalForRouteCompulsory,
  mergeRouteCompulsoryIntoConfig,
} from "@/lib/documentExtractionFields";
import { matchRulesFormForTemplate } from "@/lib/shippedTemplateMatchRules";
import { syncClassifierFromRecognition } from "@/lib/documentTypeRecognition";

export type { RouteConfidencePreset, RecognitionSignalOption };

export const ROUTE_CONFIDENCE_VALUES: Record<RouteConfidencePreset, number> = {
  flexible: 0.55,
  standard: 0.65,
  strict: 0.75,
};

type ShippedCatalogRow = {
  code: string;
  title: string;
  shortTitle: string;
  klass: DocumentTypeClass;
  posting: string;
  purchaseBundleRole?: string;
  salesBundleRole?: string;
  bundleMandatory?: string[];
  bundleConditional?: string[];
};

type DefaultsRow = {
  required_fields?: string[];
  absent_fields?: string[];
  min_route_confidence?: number;
  validation_profile?: string;
  playbook_profile?: string;
};

type ClassifierPresetRow = {
  enabled: boolean;
  priority: number;
  confidence: number;
  root: DocumentTypeClassifier["root"];
};

const SHIPPED_ROWS = shippedCatalog as ShippedCatalogRow[];
const DEFAULTS_INDEX = shippedDefaults as Record<string, DefaultsRow>;
const CLASSIFIER_PRESETS = classifierPresets as Record<string, ClassifierPresetRow>;

export const SHIPPED_DOCUMENT_TYPE_CODES = SHIPPED_ROWS.map((row) => row.code.toUpperCase()) as [
  string,
  ...string[],
];

export type ShippedDocumentTypeCode = (typeof SHIPPED_DOCUMENT_TYPE_CODES)[number];
export type DocumentTypeTemplateId = ShippedDocumentTypeCode | "custom";

export type DocumentTypeTemplate = {
  id: DocumentTypeTemplateId;
  label: string;
  description: string;
  shippedCode: string;
  routeTarget: string;
  klass: DocumentTypeClass;
  posting: string;
  playbookProfile: PlaybookProfile;
  purchaseBundleRole: PurchaseBundleRole;
  salesBundleRole: SalesBundleRole;
  classifierPriority: number;
  classifierLayout: ClassifierLayout;
  signals: RecognitionSignalOption[];
  defaultSignalIds: RecognitionSignalId[];
  defaultExtractionFields: string[];
  defaultRouteConfidence: RouteConfidencePreset;
  validationProfile: string;
  usesShippedClassifier: boolean;
};

function defaultsRowForCode(code: string): DefaultsRow {
  return DEFAULTS_INDEX[code.trim().toUpperCase()] ?? {};
}

function routeConfidenceFromValue(value: number | undefined): RouteConfidencePreset {
  if (value === undefined) return "standard";
  if (value <= 0.58) return "flexible";
  if (value >= 0.72) return "strict";
  return "standard";
}

function extractionFieldsForCode(code: string, signalMetaExtraction?: string[]): string[] {
  if (signalMetaExtraction?.length) return [...signalMetaExtraction];
  const row = defaultsRowForCode(code);
  const required = row.required_fields ?? [];
  if (required.length) return [...required];
  return [];
}

function buildTemplateFromShippedRow(row: ShippedCatalogRow): DocumentTypeTemplate {
  const code = row.code.toUpperCase();
  const signalMeta = templateSignalMetaForCode(code);
  const defaults = defaultsRowForCode(code);
  const preset = CLASSIFIER_PRESETS[code];
  const playbookProfile =
    (defaults.playbook_profile as PlaybookProfile | undefined) ||
    defaultPlaybookProfileForCode(code);

  const classifierLayout = signalMeta?.classifierLayout ?? "any_signal";
  const signals = signalMeta?.signals ?? [];
  const defaultSignalIds = signalMeta?.defaultSignalIds ?? [];
  const minConfidence = defaults.min_route_confidence;
  const routeConfidence =
    signalMeta?.routeConfidence ?? routeConfidenceFromValue(minConfidence);

  return {
    id: code as DocumentTypeTemplateId,
    label: row.title || row.shortTitle,
    description: row.title || row.shortTitle,
    shippedCode: code,
    routeTarget: routeTargetForDocumentTypeCode(code),
    klass: row.klass,
    posting: row.posting,
    playbookProfile,
    purchaseBundleRole: (signalMeta?.purchaseBundleRole ||
      row.purchaseBundleRole ||
      "") as PurchaseBundleRole,
    salesBundleRole: (signalMeta?.salesBundleRole ||
      row.salesBundleRole ||
      "") as SalesBundleRole,
    classifierPriority: preset?.priority ?? 50,
    classifierLayout,
    signals,
    defaultSignalIds,
    defaultExtractionFields: extractionFieldsForCode(code, signalMeta?.extractionFields),
    defaultRouteConfidence: routeConfidence,
    validationProfile: defaults.validation_profile ?? "",
    usesShippedClassifier: Boolean(preset),
  };
}

export const DOCUMENT_TYPE_TEMPLATES: DocumentTypeTemplate[] = [
  ...SHIPPED_ROWS.map(buildTemplateFromShippedRow),
  {
    id: "custom",
    label: "Custom type",
    description: "Blank type with recognition signals or prompt and processing sections.",
    shippedCode: "",
    routeTarget: "Vault",
    klass: "Non-transactional",
    posting: "No",
    playbookProfile: "standard_transactional",
    purchaseBundleRole: "",
    salesBundleRole: "",
    classifierPriority: 100,
    classifierLayout: "any_signal",
    signals: [],
    defaultSignalIds: [],
    defaultExtractionFields: [],
    defaultRouteConfidence: "standard",
    validationProfile: "",
    usesShippedClassifier: false,
  },
];

export function getDocumentTypeTemplate(id: DocumentTypeTemplateId): DocumentTypeTemplate {
  return DOCUMENT_TYPE_TEMPLATES.find((row) => row.id === id) ?? DOCUMENT_TYPE_TEMPLATES.at(-1)!;
}

function shippedRowForCode(code: string) {
  return SHIPPED_ROWS.find((row) => row.code.toUpperCase() === code.toUpperCase());
}

/** Simple classifier presets derived from shipped template signals (for JSON seed files). */
export function shippedClassifierPresets(): Record<string, ClassifierPresetRow> {
  const out: Record<string, ClassifierPresetRow> = {};
  for (const template of DOCUMENT_TYPE_TEMPLATES) {
    if (template.id === "custom" || !template.shippedCode) continue;
    const code = template.shippedCode.toUpperCase();
    const preset = CLASSIFIER_PRESETS[code];
    const form = matchRulesFormForTemplate(template);
    out[code] = {
      enabled: true,
      priority: preset?.priority ?? template.classifierPriority,
      confidence: preset?.confidence ?? 0.85,
      root: compileMatchRulesToClassifier(form),
    };
  }
  return out;
}

/** Org catalogue codes always follow the org sequence — never the shipped matrix code. */
function orgCodeForNewType(existing: DocumentTypeDefinition[]): string {
  return nextOrgDocumentTypeCode(existing);
}

/** Map shipped matrix ids (e.g. DT-02) to org codes where matrixTemplateCode matches. */
export function resolveBundleCodesFromMatrix(
  existing: DocumentTypeDefinition[],
  matrixCodes: string[]
): string[] {
  const resolved: string[] = [];
  for (const raw of matrixCodes) {
    const token = raw.trim().toUpperCase();
    if (!token) continue;
    const match = existing.find(
      (dt) => (dt.matrixTemplateCode ?? "").trim().toUpperCase() === token
    );
    if (match?.code) {
      resolved.push(match.code.trim().toUpperCase());
    }
  }
  return resolved;
}

export function inferTemplateIdFromDefinition(
  definition: Pick<DocumentTypeDefinition, "classifier"> & {
    matrixTemplateCode?: string;
  }
): DocumentTypeTemplateId {
  const stored = definition.matrixTemplateCode?.trim().toUpperCase();
  if (stored) {
    const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.id === stored);
    if (template && template.id !== "custom") {
      return template.id as DocumentTypeTemplateId;
    }
  }

  for (const template of DOCUMENT_TYPE_TEMPLATES) {
    if (template.id === "custom" || template.signals.length === 0) continue;
    const allowed = template.signals.map((signal) => signal.id);
    const parsed = parseSignalsFromClassifier(definition.classifier.root, allowed);
    const layout = inferClassifierLayout(definition.classifier.root);
    if (parsed.length > 0 && layout === template.classifierLayout) {
      return template.id;
    }
  }
  return "custom";
}

export function documentTypeFromTemplate(
  templateId: DocumentTypeTemplateId,
  existing: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  const template = getDocumentTypeTemplate(templateId);
  const base = createBlankDocumentType(existing);
  const shipped = template.shippedCode ? shippedRowForCode(template.shippedCode) : null;
  const preset = playbookPresetForProfile(template.playbookProfile);
  const defaults = template.shippedCode ? defaultsRowForCode(template.shippedCode) : {};
  const matchForm =
    templateId === "custom" ? null : matchRulesFormForTemplate(template);
  const defaultSignals = [...template.defaultSignalIds];
  const classifier =
    templateId === "custom"
      ? base.classifier
      : buildClassifierFromSignals(defaultSignals, template.classifierLayout, {
          priority: CLASSIFIER_PRESETS[template.shippedCode.toUpperCase()]?.priority ??
            template.classifierPriority,
          confidence: CLASSIFIER_PRESETS[template.shippedCode.toUpperCase()]?.confidence ?? 0.85,
          enabled: defaultSignals.length > 0,
        });
  const code = orgCodeForNewType(existing);
  const matrixTemplateCode =
    templateId !== "custom" && template.shippedCode ? template.shippedCode.toUpperCase() : "";
  const baseRequired = defaults.required_fields?.length
    ? [...defaults.required_fields]
    : template.shippedCode
      ? defaultCompulsoryForTemplate(template.shippedCode)
      : [...template.defaultExtractionFields];
  const absentFields = defaults.absent_fields?.length
    ? [...defaults.absent_fields]
    : matchForm
      ? absentFieldsFromExcludeRules(matchForm.excludeRules)
      : [];
  const baseExtraction =
    templateId === "custom" ? [] : [...template.defaultExtractionFields];
  const mergedFields = mergeRouteCompulsoryIntoConfig({
    requiredFields: baseRequired,
    extractionFields: baseExtraction,
    routeTarget: template.routeTarget,
    transactional: isTransactionalForRouteCompulsory({
      posting: template.posting,
      playbookProfile: template.playbookProfile,
    }),
  });
  const extractionFields = mergedFields.extractionFields;
  const requiredFields = mergedFields.requiredFields;
  const payload: DocumentTypeDefinition = {
    ...base,
    code,
    title: shipped?.title ?? (templateId === "custom" ? "" : template.label),
    shortTitle: shipped?.shortTitle ?? (templateId === "custom" ? "" : template.label),
    recognitionMode: "signals",
    recognitionSignals: templateId === "custom" ? [] : [...defaultSignals],
    llmPrompt: "",
    klass: template.klass,
    posting: template.posting,
    routeTarget: template.routeTarget,
    playbookProfile: template.playbookProfile,
    matchPolicy: { mode: preset.matchMode },
    approvalPolicy: { mode: preset.approvalMode },
    purchaseBundleRole: template.purchaseBundleRole,
    salesBundleRole: template.salesBundleRole,
    validationProfile:
      templateId === "custom" ? "non_actionable" : template.validationProfile,
    extractionFields,
    requiredFields,
    absentFields,
    minRouteConfidence:
      templateId === "custom"
        ? 0.75
        : defaults.min_route_confidence ?? ROUTE_CONFIDENCE_VALUES[template.defaultRouteConfidence],
    classifier,
    matrixTemplateCode,
    enabled: true,
    bundleMandatory: (() => {
      const shippedMandatory = shipped?.bundleMandatory ?? [];
      if (!shippedMandatory.length) return [];
      const resolved = resolveBundleCodesFromMatrix(existing, shippedMandatory);
      return resolved.length === shippedMandatory.length ? resolved : [...shippedMandatory];
    })(),
    bundleConditional: (() => {
      const shippedConditional = normalizeBundleConditional(shipped?.bundleConditional ?? []);
      if (!shippedConditional.length) return [];
      const resolved = resolveBundleCodesFromMatrix(existing, shippedConditional);
      return resolved.length === shippedConditional.length ? resolved : [...shippedConditional];
    })(),
    postTo: {
      ...emptyDocumentTypePostTo(),
      ledger: "",
    },
  };

  if (templateId === "custom") {
    return syncClassifierFromRecognition(payload);
  }

  return syncClassifierFromRecognition({
    ...payload,
    enabled: true,
  });
}

export function applyTemplateSignalsToClassifier(
  template: DocumentTypeTemplate,
  selectedSignalIds: RecognitionSignalId[]
): DocumentTypeDefinition["classifier"] {
  return buildClassifierFromSignals(selectedSignalIds, template.classifierLayout, {
    priority: template.classifierPriority,
    enabled: true,
    confidence: 0.85,
  });
}

export function routeConfidencePreset(value: number): RouteConfidencePreset {
  return routeConfidenceFromValue(value);
}
