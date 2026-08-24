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

  return (
    <div
      className={cn(
        "flex h-full min-h-0 shrink-0 items-center justify-end",
        highlighted && "rounded-md px-1"
      )}
      data-testid={testId}
    >
      <Switch
        id={switchId}
        checked={running}
        disabled={!editable || !onToggle}
        onCheckedChange={(checked) => onToggle?.(stepId, checked)}
        aria-label={`${running ? "Run" : "Skip"} ${label} on next reprocess`}
      />
    </div>
  );
}
