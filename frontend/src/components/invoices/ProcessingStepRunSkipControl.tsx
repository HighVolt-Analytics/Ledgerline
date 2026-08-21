import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import type { ProcessingOverrideStepId } from "@/lib/processingOverrides";

type ProcessingStepRunSkipControlProps = {
  stepId: ProcessingOverrideStepId;
  label: string;
  running: boolean;
  editable: boolean;
  highlighted?: boolean;
  controlKey?: string;
  onToggle?: (stepId: ProcessingOverrideStepId, run: boolean) => void;
};

export function ProcessingStepRunSkipControl({
  stepId,
  label,
  running,
  editable,
  highlighted = false,
  controlKey,
  onToggle,
}: ProcessingStepRunSkipControlProps) {
  const testId = `processing-override-row-${controlKey ?? stepId}`;
  const switchId = `override-${controlKey ?? stepId}`;

  if (editable && onToggle) {
    return (
      <div
        className={cn(
          "flex shrink-0 flex-col items-end gap-1",
          highlighted && "rounded-md px-1"
        )}
        data-testid={testId}
      >
        <Switch
          id={switchId}
          checked={running}
          onCheckedChange={(checked) => onToggle(stepId, checked)}
          aria-label={`Run ${label}`}
        />
        <span className="text-[10px] text-muted-foreground">
          {running ? "Run" : "Skip"}
        </span>
      </div>
    );
  }

  return (
    <span
      className={cn(
        "shrink-0 text-xs font-medium",
        running ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
      )}
      data-testid={testId}
    >
      {running ? "Run" : "Skip"}
    </span>
  );
}
