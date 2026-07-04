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
import {
  computeDropdownMenuPosition,
  DROPDOWN_MENU_Z_INDEX,
  type DropdownMenuPosition,
} from "@/lib/dropdownPortal";
import { notifySelectClosed, notifySelectOpened } from "@/components/ui/selectCoordinator";

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
  options = [],
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
  const [menuStyle, setMenuStyle] = useState<DropdownMenuPosition | null>(null);

  const selected = options.find((o) => o.value === value);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    setMenuStyle(computeDropdownMenuPosition(trigger));
  }, []);

  const closeMenu = useCallback(() => {
    setOpen(false);
    notifySelectClosed(listId);
  }, [listId]);

  const openMenu = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger || disabled) return;
    notifySelectOpened(listId, closeMenu);
    setMenuStyle(computeDropdownMenuPosition(trigger));
    setOpen(true);
  }, [disabled, listId, closeMenu]);

  useEffect(() => {
    return () => {
      notifySelectClosed(listId);
    };
  }, [listId]);

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
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      closeMenu();
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, closeMenu]);

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
      event.preventDefault();
      openMenu();
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
        onClick={() => {
          if (disabled) return;
          if (open) closeMenu();
          else openMenu();
        }}
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

      {open && menuStyle
        ? createPortal(
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
                maxHeight: menuStyle.maxHeight,
                zIndex: DROPDOWN_MENU_Z_INDEX,
              }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {options.map((option, index) => {
                const isSelected = option.value === value;
                return (
                  <button
                    key={`${listId}-${index}-${option.label}`}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    data-selected={isSelected ? "true" : undefined}
                    className={cn("app-dropdown-option", size === "md" && "app-dropdown-option--md")}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      onValueChange(option.value);
                      closeMenu();
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
            </div>,
            document.body
          )
        : null}
    </>
  );
}
