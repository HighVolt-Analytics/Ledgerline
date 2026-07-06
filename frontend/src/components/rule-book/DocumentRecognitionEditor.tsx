import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { MatchRulesPanel } from "@/components/rule-book/MatchRulesPanel";
import { applyLlmPrompt, applyRecognitionMode } from "@/lib/documentTypeRecognition";
import type { DocumentTypeDefinition, RecognitionMode } from "@/lib/v5DocumentTypes";

const RECOGNITION_MODES: Array<{ id: RecognitionMode; label: string; hint: string }> = [
  {
    id: "signals",
    label: "Recognition signals",
    hint: "Match when / do not match if rules on OCR and extracted fields.",
  },
  {
    id: "prompt",
    label: "Prompt",
    hint: "Describe how to recognise this document in your own words for the AI classifier.",
  },
];

type DocumentRecognitionEditorProps = {
  draft: DocumentTypeDefinition;
  onChange: (next: DocumentTypeDefinition) => void;
};

export function DocumentRecognitionEditor({ draft, onChange }: DocumentRecognitionEditorProps) {
  const mode = draft.recognitionMode ?? "signals";

  const setCatalogueEnabled = (enabled: boolean) => {
    onChange({ ...draft, enabled });
  };

  const switchMode = (nextMode: RecognitionMode) => {
    onChange(applyRecognitionMode(draft, nextMode));
  };

  return (
    <div className="space-y-4" data-testid="document-recognition-editor">
      <div className="flex items-center gap-2">
        <Switch id="dt-ai-enabled" checked={draft.enabled} onCheckedChange={setCatalogueEnabled} />
        <label htmlFor="dt-ai-enabled" className="cursor-pointer text-sm text-foreground">
          Include in AI classification catalogue
        </label>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-medium text-foreground">How should we recognise this type?</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {RECOGNITION_MODES.map((option) => (
            <button
              key={option.id}
              type="button"
              className={cn(
                "rounded-lg border p-3 text-left transition-colors",
                mode === option.id
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/30"
              )}
              onClick={() => switchMode(option.id)}
            >
              <span className="block text-sm font-medium text-foreground">{option.label}</span>
              <span className="mt-1 block text-[11px] leading-snug text-muted-foreground">
                {option.hint}
              </span>
            </button>
          ))}
        </div>
      </div>

      {mode === "signals" ? (
        <MatchRulesPanel draft={draft} onChange={onChange} />
      ) : (
        <div className="space-y-1.5 rounded-md border border-border bg-muted/20 p-3">
          <label htmlFor="dt-llm-prompt" className="text-xs font-medium text-foreground">
            Recognition prompt
          </label>
          <textarea
            id="dt-llm-prompt"
            rows={4}
            value={draft.llmPrompt ?? ""}
            onChange={(e) => onChange(applyLlmPrompt(draft, e.target.value))}
            placeholder="e.g. Goods received note with PO reference; often handwritten. Not a tax invoice."
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <p className="text-[11px] text-muted-foreground">
            The AI uses this description when choosing this document type. Write at least 20 characters.
          </p>
        </div>
      )}
    </div>
  );
}
