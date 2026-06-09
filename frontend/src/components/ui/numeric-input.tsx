import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { Input } from "./input";

function parseDigits(raw: string, optional: boolean): number | undefined {
  const digits = raw.replace(/\D/g, "");
  if (digits === "") return optional ? undefined : 0;
  const parsed = parseInt(digits, 10);
  return Number.isNaN(parsed) ? (optional ? undefined : 0) : parsed;
}

function formatDisplay(
  value: number | undefined,
  optional: boolean,
  hideZero: boolean
): string {
  if (optional) {
    return value === undefined ? "" : String(value);
  }
  if (value === undefined || (hideZero && value === 0)) return "";
  return String(value);
}

export function NumericInput({
  value,
  onValueChange,
  optional = false,
  hideZero = true,
  min = 0,
  step = 1,
  disabled,
  showSteppers = true,
  className,
  wrapperClassName,
  "data-testid": testId,
}: {
  value: number | undefined;
  onValueChange: (value: number | undefined) => void;
  optional?: boolean;
  hideZero?: boolean;
  min?: number;
  step?: number;
  disabled?: boolean;
  showSteppers?: boolean;
  className?: string;
  wrapperClassName?: string;
  "data-testid"?: string;
}) {
  const current = value ?? (optional ? undefined : 0);

  const applyStep = (delta: number) => {
    const base = current ?? 0;
    onValueChange(Math.max(min, base + delta * step));
  };

  const steppersEnabled = showSteppers && !disabled;

  return (
    <div className={cn("app-numeric-input-wrap", steppersEnabled && "has-steppers", wrapperClassName)}>
      <Input
        type="text"
        inputMode="numeric"
        disabled={disabled}
        value={formatDisplay(value, optional, hideZero)}
        onChange={(e) => {
          const parsed = parseDigits(e.target.value, optional);
          if (parsed === undefined) {
            onValueChange(undefined);
            return;
          }
          onValueChange(Math.max(min, parsed));
        }}
        data-testid={testId}
        className={cn("app-numeric-input min-w-0 w-full text-left tnum font-mono", className)}
      />
      {steppersEnabled && (
        <div className="app-numeric-input-steppers" aria-hidden>
          <button
            type="button"
            tabIndex={-1}
            className="app-numeric-input-step"
            onClick={() => applyStep(1)}
            aria-label="Increase value"
          >
            <ChevronUp className="h-2.5 w-2.5" strokeWidth={2} />
          </button>
          <button
            type="button"
            tabIndex={-1}
            className="app-numeric-input-step"
            onClick={() => applyStep(-1)}
            aria-label="Decrease value"
          >
            <ChevronDown className="h-2.5 w-2.5" strokeWidth={2} />
          </button>
        </div>
      )}
    </div>
  );
}
