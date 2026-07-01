import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import {
  PROCESSING_OVERRIDE_STEPS,
  type ProcessingOverrideStepId,
} from "@/lib/processingOverrides";

type InvoiceProcessingOverridesSectionProps = {
  skipSteps: ProcessingOverrideStepId[];
  editable: boolean;
  failedStage?: string | null;
  onToggle?: (stepId: ProcessingOverrideStepId, run: boolean) => void;
};

function stageHintsFailedStage(failedStage: string | null | undefined): ProcessingOverrideStepId | null {
  if (!failedStage) return null;
  const lower = failedStage.toLowerCase();
  if (lower.includes("valid")) return "validation";
  if (lower.includes("map")) return "mapping_review";
  if (lower.includes("pars")) return "image_quality";
  if (lower.includes("classif")) return "classification";
  return null;
}

export function InvoiceProcessingOverridesSection({
  skipSteps,
  editable,
  failedStage,
  onToggle,
}: InvoiceProcessingOverridesSectionProps) {
  const highlighted = stageHintsFailedStage(failedStage);
  const skipSet = new Set(skipSteps);

  return (
    <div className="space-y-4" data-testid="processing-overrides-section">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Processing overrides</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {editable
            ? "Unchecked steps are skipped on the next reprocess or approve. Save changes or use Reprocess / Approve to apply."
            : "Steps skipped on reprocess are shown below. Open this tab or click Edit to change them."}
        </p>
      </div>

      <ul className="space-y-3">
        {PROCESSING_OVERRIDE_STEPS.map((step) => {
          const running = !skipSet.has(step.id);
          const highlightedRow = highlighted === step.id;
          return (
            <li
              key={step.id}
              className={cn(
                "flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2.5",
                highlightedRow && "border-destructive/40 bg-destructive/5"
              )}
              data-testid={`processing-override-row-${step.id}`}
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-foreground">{step.label}</div>
                <p className="mt-0.5 text-xs text-muted-foreground">{step.hint}</p>
                {!running && (
                  <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-400">
                    Skipped on reprocess
                  </p>
                )}
              </div>
              {editable && onToggle ? (
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Switch
                    id={`override-${step.id}`}
                    checked={running}
                    onCheckedChange={(checked) => onToggle(step.id, checked)}
                    aria-label={`Run ${step.label}`}
                  />
                  <span className="text-[10px] text-muted-foreground">
                    {running ? "Run" : "Skip"}
                  </span>
                </div>
              ) : (
                <span
                  className={cn(
                    "shrink-0 text-xs font-medium",
                    running ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
                  )}
                >
                  {running ? "Run" : "Skip"}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
