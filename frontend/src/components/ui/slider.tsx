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
        "relative flex w-full touch-none select-none items-center",
        disabled && "pointer-events-none opacity-50",
        className
      )}
      {...props}
    >
      <div
        ref={trackRef}
        className="relative h-2 w-full grow overflow-hidden rounded-full bg-secondary"
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
        <div className="absolute h-full bg-primary" style={{ width: `${pct}%` }} />
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
        className="pointer-events-none absolute top-1/2 z-0 h-5 w-5 -translate-y-1/2 rounded-full border-2 border-primary bg-background shadow-sm transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background"
        style={{ left: `calc(${pct}% - 10px)` }}
      />
    </div>
  );
}
