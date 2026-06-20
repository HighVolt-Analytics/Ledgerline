/**
 * User-facing document type templates for the Rule Book catalogue.
 * Built from the shipped Excel / v5 matrix (v5DocumentTypes.json).
 */

import shippedCatalog from "@/lib/v5DocumentTypes.json";
import shippedDefaults from "@/lib/documentTypeDefaults.json";
import classifierPresets from "@/lib/documentTypeClassifierPresets.json";
import {
  buildClassifierFromSignals,
  inferClassifierLayout,
  parseSignalsFromClassifier,
  type ClassifierLayout,
  type RecognitionSignalId,
} from "@/lib/documentClassifierBuilder";
import { playbookPresetForProfile, type PlaybookProfile } from "@/lib/documentPlaybookConfig";
import type {
  DocumentTypeClass,
  DocumentTypeDefinition,
  DocumentTypeClassifier,
  DocumentTypeFraudRisk,
} from "@/lib/v5DocumentTypes";
import { createBlankDocumentType, nextOrgDocumentTypeCode } from "@/lib/v5DocumentTypes";
import type { PurchaseBundleRole } from "@/lib/documentBundleConfig";
import { routeTargetForDocumentTypeCode } from "@/lib/documentTypeRouteTargets";
import { defaultPlaybookProfileForCode } from "@/lib/documentTypePlaybookDefaults";
import {
  templateSignalMetaForCode,
  type RecognitionSignalOption,
  type RouteConfidencePreset,
} from "@/lib/documentTypeTemplateMeta";

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
  fraudRisk: DocumentTypeFraudRisk;
  oneLine: string;
  purchaseBundleRole?: string;
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
  fraudRisk: DocumentTypeFraudRisk;
  playbookProfile: PlaybookProfile;
  purchaseBundleRole: PurchaseBundleRole;
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
    label: row.shortTitle || row.title,
    description: row.oneLine,
    shippedCode: code,
    routeTarget: routeTargetForDocumentTypeCode(code),
    klass: row.klass,
    posting: row.posting,
    fraudRisk: row.fraudRisk,
    playbookProfile,
    purchaseBundleRole: (signalMeta?.purchaseBundleRole ||
      row.purchaseBundleRole ||
      "") as PurchaseBundleRole,
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
    description: "Start blank and configure recognition manually.",
    shippedCode: "",
    routeTarget: "Vault",
    klass: "Transactional",
    posting: "No",
    fraudRisk: "low",
    playbookProfile: "standard_transactional",
    purchaseBundleRole: "",
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

function classifierFromTemplate(template: DocumentTypeTemplate): DocumentTypeClassifier {
  const preset = template.shippedCode
    ? CLASSIFIER_PRESETS[template.shippedCode.toUpperCase()]
    : undefined;

  if (preset) {
    return {
      enabled: preset.enabled,
      priority: preset.priority,
      confidence: preset.confidence,
      root: preset.root,
    };
  }

  if (template.defaultSignalIds.length > 0) {
    return buildClassifierFromSignals(
      template.defaultSignalIds,
      template.classifierLayout,
      {
        priority: template.classifierPriority,
        enabled: true,
        confidence: 0.85,
      }
    );
  }

  return createBlankDocumentType([]).classifier;
}

/** Org catalogue codes always follow the org sequence — never the shipped matrix code. */
function orgCodeForNewType(existing: DocumentTypeDefinition[]): string {
  return nextOrgDocumentTypeCode(existing);
}

export function inferTemplateIdFromDefinition(
  definition: Pick<DocumentTypeDefinition, "classifier" | "matrixTemplateCode">
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
  const classifier = classifierFromTemplate(template);
  const code = orgCodeForNewType(existing);
  const matrixTemplateCode =
    templateId !== "custom" && template.shippedCode ? template.shippedCode.toUpperCase() : "";
  const requiredFields = defaults.required_fields?.length
    ? [...defaults.required_fields]
    : [...template.defaultExtractionFields];
  const absentFields = defaults.absent_fields?.length ? [...defaults.absent_fields] : [];

  return {
    ...base,
    code,
    title: shipped?.title ?? template.label,
    shortTitle: shipped?.shortTitle ?? template.label,
    oneLine: shipped?.oneLine ?? template.description,
    klass: template.klass,
    posting: template.posting,
    fraudRisk: template.fraudRisk,
    routeTarget: template.routeTarget,
    playbookProfile: template.playbookProfile,
    matchPolicy: { mode: preset.matchMode },
    approvalPolicy: { mode: preset.approvalMode },
    purchaseBundleRole: template.purchaseBundleRole,
    validationProfile: template.validationProfile,
    extractionFields: [...template.defaultExtractionFields],
    requiredFields,
    absentFields,
    minRouteConfidence:
      defaults.min_route_confidence ?? ROUTE_CONFIDENCE_VALUES[template.defaultRouteConfidence],
    classifier,
    classifierCustomized: false,
    matrixTemplateCode,
    enabled: true,
    bundleMandatory: shipped?.bundleMandatory ? [...shipped.bundleMandatory] : [],
    bundleConditional: shipped?.bundleConditional ? [...shipped.bundleConditional] : [],
  };
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
