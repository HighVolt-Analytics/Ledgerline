import { useCallback, useId, useRef } from "react";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

function snapValue(n: number, min: number, max: number, step: number) {
  const bounded = clamp(n, min, max);
  if (step <= 0) return bounded;
  const steps = Math.round((bounded - min) / step);
  return clamp(min + steps * step, min, max);
}

export function Slider({
  value,
  min = 0,
  max = 100,
  step = 1,
  onValueChange,
  disabled,
  className,
  ...props
}: {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onValueChange?: (value: number) => void;
  disabled?: boolean;
  className?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, "onChange">) {
  const inputId = useId();
  const trackRef = useRef<HTMLDivElement>(null);
  const span = max - min;
  const pct = span === 0 ? 0 : ((value - min) / span) * 100;

  const updateFromPointer = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track || disabled || !onValueChange) return;
      const { left, width } = track.getBoundingClientRect();
      const ratio = width > 0 ? (clientX - left) / width : 0;
      onValueChange(snapValue(min + ratio * span, min, max, step));
    },
    [disabled, max, min, onValueChange, span, step]
  );

  return (
    <div
      className={cn(
        "relative flex h-4 w-full touch-none select-none items-center",
        disabled && "pointer-events-none opacity-50",
        className
      )}
      {...props}
    >
      <div
        ref={trackRef}
        className="app-slider-track relative h-px w-full grow rounded-full"
        onPointerDown={(e) => {
          if (disabled) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          updateFromPointer(e.clientX);
        }}
        onPointerMove={(e) => {
          if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
          updateFromPointer(e.clientX);
        }}
        onPointerUp={(e) => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) {
            e.currentTarget.releasePointerCapture(e.pointerId);
          }
        }}
      >
        <div className="app-slider-track-fill absolute h-full rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <input
        id={inputId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        onChange={(e) => onValueChange?.(Number(e.target.value))}
        className="app-slider-input peer absolute inset-0 z-10 h-full w-full cursor-pointer"
      />
      <div
        className="app-slider-thumb pointer-events-none absolute top-1/2 z-0 h-2.5 w-2.5 -translate-y-1/2 rounded-full transition-colors peer-focus-visible:ring-1 peer-focus-visible:ring-ring/60"
        style={{ left: `calc(${pct}% - 5px)` }}
      />
    </div>
  );
}
