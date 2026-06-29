import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  computeDropdownMenuPosition,
  DROPDOWN_MENU_Z_INDEX,
  type DropdownMenuPosition,
} from "@/lib/dropdownPortal";
import {
  CUSTOM_MATCH_RULE_FIELD,
  MATCH_RULE_FIELD_GROUPS,
  matchRuleFieldLabel,
  type MatchRuleFieldGroup,
} from "@/lib/documentMatchRules";

export { CUSTOM_MATCH_RULE_FIELD };

type MatchRuleFieldSelectProps = {
  value: string;
  onValueChange: (value: string) => void;
  groups?: MatchRuleFieldGroup[];
  className?: string;
  disabled?: boolean;
};

function filterGroups(groups: MatchRuleFieldGroup[], query: string): MatchRuleFieldGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return groups;
  return groups
    .map((group) => ({
      ...group,
      fields: group.fields.filter(
        (field) =>
          field.label.toLowerCase().includes(q) ||
          field.key.toLowerCase().includes(q) ||
          (field.description?.toLowerCase().includes(q) ?? false)
      ),
    }))
    .filter((group) => group.fields.length > 0);
}

export function MatchRuleFieldSelect({
  value,
  onValueChange,
  groups = MATCH_RULE_FIELD_GROUPS,
  className,
  disabled,
}: MatchRuleFieldSelectProps) {
  const listId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [menuStyle, setMenuStyle] = useState<DropdownMenuPosition | null>(null);

  const filteredGroups = useMemo(() => filterGroups(groups, query), [groups, query]);
  const selectedLabel = matchRuleFieldLabel(value);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    setMenuStyle(
      computeDropdownMenuPosition(trigger, { minWidth: 280, maxHeight: 360 })
    );
  }, []);

  const closeMenu = useCallback(() => {
    setOpen(false);
    setQuery("");
  }, []);

  const openMenu = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger || disabled) return;
    setMenuStyle(
      computeDropdownMenuPosition(trigger, { minWidth: 280, maxHeight: 360 })
    );
    setOpen(true);
  }, [disabled]);

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
    const timer = window.setTimeout(() => searchRef.current?.focus(), 50);
    return () => window.clearTimeout(timer);
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
        className={cn(
          "inline-flex max-w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-2 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
      >
        <span className={cn("truncate text-left", !value && "text-muted-foreground")}>
          {value ? selectedLabel : "Select field…"}
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
              className="match-rule-field-menu fixed"
              style={{
                top: menuStyle.top,
                left: menuStyle.left,
                width: menuStyle.width,
                minWidth: menuStyle.width,
                zIndex: DROPDOWN_MENU_Z_INDEX,
              }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <div className="border-b border-border p-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <input
                    ref={searchRef}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search fields…"
                    className="h-8 w-full rounded-md border border-input bg-background py-1 pl-7 pr-2 text-xs"
                  />
                </div>
              </div>
              <div
                className="overflow-y-auto p-1"
                style={{ maxHeight: Math.max(120, menuStyle.maxHeight - 52) }}
              >
                {filteredGroups.length === 0 ? (
                  <p className="px-2 py-3 text-center text-xs text-muted-foreground">No fields match</p>
                ) : (
                  filteredGroups.map((group) => (
                    <div key={group.id} className="pb-1">
                      <p
                        className="sticky top-0 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
                        style={{ backgroundColor: "hsl(var(--popover))" }}
                      >
                        {group.label}
                      </p>
                      {group.fields.map((field) => {
                        const isSelected = field.key === value;
                        return (
                          <button
                            key={field.key}
                            type="button"
                            role="option"
                            aria-selected={isSelected}
                            data-selected={isSelected ? "true" : undefined}
                            className={cn(
                              "app-dropdown-option w-full text-left",
                              isSelected && "bg-accent/65 font-semibold"
                            )}
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => {
                              onValueChange(field.key);
                              closeMenu();
                            }}
                          >
                            <span className="min-w-0 flex-1">
                              <span className="block truncate">{field.label}</span>
                              {field.description ? (
                                <span className="block truncate text-[10px] font-normal text-muted-foreground">
                                  {field.description}
                                </span>
                              ) : null}
                            </span>
                            {isSelected ? (
                              <Check
                                className="h-3.5 w-3.5 shrink-0 text-[hsl(var(--chart-1))]"
                                strokeWidth={2.5}
                              />
                            ) : null}
                          </button>
                        );
                      })}
                    </div>
                  ))
                )}
                <div className="border-t border-border pt-1">
                  <button
                    type="button"
                    role="option"
                    className="app-dropdown-option w-full text-left text-muted-foreground"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      onValueChange(CUSTOM_MATCH_RULE_FIELD);
                      closeMenu();
                    }}
                  >
                    <span className="truncate">Custom field name…</span>
                  </button>
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
