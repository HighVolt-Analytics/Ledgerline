import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

export type SelectOption = { value: string; label: string };

export function toSelectOptions(items: readonly string[]): SelectOption[] {
  return items.map((value) => ({ value, label: value }));
}

const triggerBase =
  "inline-flex max-w-full items-center justify-between gap-2 rounded-md border border-input bg-background shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

const triggerSize = {
  sm: "h-8 px-2 text-xs",
  md: "h-9 px-3 text-sm",
} as const;

type SelectProps = {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  id?: string;
  "data-testid"?: string;
  size?: keyof typeof triggerSize;
};

export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  className,
  disabled,
  id,
  "data-testid": testId,
  size = "sm",
}: SelectProps) {
  const listId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState({ top: 0, left: 0, width: 0 });

  const selected = options.find((o) => o.value === value);

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMenuStyle({
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
    });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const selectedEl = menuRef.current?.querySelector('[data-selected="true"]');
    if (selectedEl instanceof HTMLElement) {
      selectedEl.scrollIntoView({ block: "nearest" });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        data-testid={testId}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => !disabled && setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        className={cn(triggerBase, triggerSize[size], className)}
      >
        <span className={cn("truncate text-left", !selected && "text-muted-foreground")}>
          {selected?.label ?? placeholder}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
            open && "rotate-180"
          )}
          strokeWidth={2}
        />
      </button>

      {open &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[240]" aria-hidden onClick={() => setOpen(false)} />
            <div
              ref={menuRef}
              id={listId}
              role="listbox"
              className="app-dropdown-menu fixed"
              style={{
                top: menuStyle.top,
                left: menuStyle.left,
                width: menuStyle.width,
                minWidth: menuStyle.width,
              }}
            >
              {options.map((option) => {
                const isSelected = option.value === value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    data-selected={isSelected ? "true" : undefined}
                    className={cn("app-dropdown-option", size === "md" && "app-dropdown-option--md")}
                    onClick={() => {
                      onValueChange(option.value);
                      setOpen(false);
                    }}
                  >
                    <span className="truncate">{option.label}</span>
                    {isSelected && (
                      <Check
                        className="h-3.5 w-3.5 shrink-0 text-[hsl(var(--chart-1))]"
                        strokeWidth={2.5}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </>,
          document.body
        )}
    </>
  );
}
