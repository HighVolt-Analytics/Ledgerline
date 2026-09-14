import { useMemo } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import {
  getDocumentTypeTemplate,
  routeConfidencePreset,
  ROUTE_CONFIDENCE_VALUES,
  type DocumentTypeTemplateId,
  type RouteConfidencePreset,
} from "@/lib/documentTypeTemplates";
import {
  allRecognitionSignalOptions,
  templateSignalMetaForCode,
  type RecognitionSignalOption,
} from "@/lib/documentTypeTemplateMeta";
import type { RecognitionSignalId } from "@/lib/documentClassifierBuilder";
import { applyRecognitionSignalIds } from "@/lib/documentTypeRecognition";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

type SimpleClassifierSectionProps = {
  draft: DocumentTypeDefinition;
  templateId: DocumentTypeTemplateId;
  onChange: (next: DocumentTypeDefinition) => void;
  onOpenAdvanced: () => void;
};

const CONFIDENCE_OPTIONS: Array<{ value: RouteConfidencePreset; label: string; hint: string }> = [
  { value: "flexible", label: "Flexible", hint: "Route when reasonably sure (~55%)" },
  { value: "standard", label: "Standard", hint: "Recommended for most types (~65%)" },
  { value: "strict", label: "Strict", hint: "Only auto-route when very confident (~75%)" },
];

export function SimpleClassifierSection({
  draft,
  templateId,
  onChange,
  onOpenAdvanced,
}: SimpleClassifierSectionProps) {
  const template = getDocumentTypeTemplate(templateId);
  const signalMeta = useMemo(() => {
    const code =
      (draft.matrixTemplateCode || "").trim() ||
      template.dictionaryCode ||
      String(templateId);
    return templateSignalMetaForCode(code);
  }, [draft.matrixTemplateCode, template.dictionaryCode, templateId]);
  const signalOptions = useMemo(
    () =>
      signalMeta && signalMeta.signals.length > 0
        ? signalMeta.signals
        : allRecognitionSignalOptions(),
    [signalMeta]
  );
  const classifierLayout = signalMeta?.classifierLayout ?? "any_signal";
  const allowedIds = useMemo(
    () => signalOptions.map((s: RecognitionSignalOption) => s.id),
    [signalOptions]
  );

  const selectedSignals = useMemo(
    () => draft.recognitionSignals as RecognitionSignalId[],
    [draft.recognitionSignals]
  );

  const confidencePreset = routeConfidencePreset(draft.minRouteConfidence ?? 0.65);

  const toggleSignal = (signalId: RecognitionSignalId, checked: boolean) => {
    const nextSet = new Set(selectedSignals);
    if (checked) nextSet.add(signalId);
    else nextSet.delete(signalId);
    const nextIds = allowedIds.filter((id) => nextSet.has(id));
    onChange(
      applyRecognitionSignalIds(
        {
          ...draft,
          recognitionMode: "signals",
        },
        nextIds
      )
    );
  };

  const setConfidencePreset = (preset: RouteConfidencePreset) => {
    onChange({ ...draft, minRouteConfidence: ROUTE_CONFIDENCE_VALUES[preset] });
  };

  return (
    <div className="space-y-4" data-testid="simple-classifier">
      <div className="flex items-center gap-2">
        <Switch
          id="dt-classifier-enabled-simple"
          checked={draft.classifier.enabled}
          onCheckedChange={(enabled) =>
            onChange({
              ...draft,
              classifier: { ...draft.classifier, enabled },
            })
          }
        />
        <label htmlFor="dt-classifier-enabled-simple" className="text-sm text-foreground cursor-pointer">
          Recognise this document type automatically
        </label>
      </div>

      {draft.classifier.enabled ? (
        <>
          <div className="space-y-2">
            <p className="text-xs font-medium text-foreground">How we spot this document</p>
            <p className="text-xs text-muted-foreground">
              Tick every signal that usually appears. A match on <strong>any</strong> ticked signal
              {classifierLayout === "all_signals"
                ? " is not enough — all ticked signals must match."
                : classifierLayout === "supporting_doc"
                  ? " is enough, and the document must not look like a tax invoice."
                  : " is enough to classify."}
            </p>
            {signalOptions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Choose a template with recognition signals, or switch to advanced mode.
              </p>
            ) : (
              <ul className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
                {signalOptions.map((signal: RecognitionSignalOption) => {
                  const checked = selectedSignals.includes(signal.id);
                  return (
                    <li key={signal.id}>
                      <label className="flex cursor-pointer items-start gap-2.5">
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 rounded border-input"
                          checked={checked}
                          onChange={(e) =>
                            toggleSignal(signal.id as RecognitionSignalId, e.target.checked)
                          }
                          data-testid={`signal-${signal.id}`}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm text-foreground">{signal.label}</span>
                          <span className="block text-xs text-muted-foreground">{signal.hint}</span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
            {selectedSignals.length === 0 && (signalMeta?.signals.length ?? 0) > 0 ? (
              <p className="text-xs ds-warning-text">
                Select at least one signal or this type will never match.
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium text-foreground">Auto-route confidence</p>
            <div className="flex flex-wrap gap-2">
              {CONFIDENCE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setConfidencePreset(option.value)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-left text-xs transition",
                    confidencePreset === option.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40"
                  )}
                  data-testid={`route-confidence-${option.value}`}
                >
                  <span className="font-medium">{option.label}</span>
                  <span className="ml-1 text-[10px] opacity-80">— {option.hint}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          When off, only purchase filename heuristics may apply — not recommended for production.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          Upload a sample on the Upload page, then review routing on the invoice in Upload or Inbox.
        </p>
        <Button type="button" size="sm" variant="outline" className="h-8" onClick={onOpenAdvanced}>
          <Settings2 className="h-3.5 w-3.5 mr-1" />
          Advanced classifier
        </Button>
      </div>
    </div>
  );
}
