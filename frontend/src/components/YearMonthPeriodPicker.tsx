import { useEffect, useId, useRef, useState } from "react";
import { CalendarDays, Check, ChevronDown } from "lucide-react";
import { formatReconMonthOnly } from "@/lib/reconciliation";
import { cn } from "@/lib/cn";

type PeriodOption = { value: string; label: string };

function PeriodMenu({
  id,
  testId,
  ariaLabel,
  value,
  displayValue,
  options,
  onChange,
  open,
  onOpenChange,
  disabled,
  segmentClass,
  menuMinWidth,
}: {
  id: string;
  testId: string;
  ariaLabel: string;
  value: string;
  displayValue: string;
  options: PeriodOption[];
  onChange: (value: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled?: boolean;
  segmentClass?: string;
  menuMinWidth?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !listRef.current) return;
    const selected = listRef.current.querySelector('[data-selected="true"]');
    if (selected instanceof HTMLElement) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, [open]);

  return (
    <div className={cn("app-period-picker-segment", segmentClass)}>
      <button
        id={id}
        type="button"
        data-testid={testId}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="app-period-picker-trigger"
      >
        <span className="truncate">{displayValue}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
            open && "rotate-180"
          )}
          strokeWidth={2}
        />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => onOpenChange(false)} aria-hidden />
          <div
            ref={listRef}
            role="listbox"
            aria-label={ariaLabel}
            className="app-period-picker-menu"
            style={menuMinWidth ? { minWidth: menuMinWidth } : undefined}
          >
            {options.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">No options</p>
            ) : (
              options.map((opt) => {
                const selected = opt.value === value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    data-selected={selected ? "true" : undefined}
                    className="app-period-picker-option"
                    onClick={() => {
                      onChange(opt.value);
                      onOpenChange(false);
                    }}
                  >
                    <span className="truncate">{opt.label}</span>
                    {selected && (
                      <Check className="dropdown-accent h-3.5 w-3.5" strokeWidth={2.5} />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function YearMonthPeriodPicker({
  year,
  monthKey,
  yearOptions,
  monthOptions,
  onYearChange,
  onMonthChange,
  disabled,
  yearId = "period-year",
  monthId = "period-month",
  yearTestId = "select-period-year",
  monthTestId = "select-period-month",
  pickerTestId = "period-picker",
}: {
  year: string;
  monthKey: string;
  yearOptions: string[];
  monthOptions: { label: string; value: string }[];
  onYearChange: (year: string) => void;
  onMonthChange: (monthKey: string) => void;
  disabled?: boolean;
  yearId?: string;
  monthId?: string;
  yearTestId?: string;
  monthTestId?: string;
  pickerTestId?: string;
}) {
  const groupId = useId();
  const [openMenu, setOpenMenu] = useState<"year" | "month" | null>(null);

  const monthDisplay =
    monthOptions.find((m) => m.value === monthKey)?.label ??
    (monthKey ? formatReconMonthOnly(monthKey) : "Month");

  const yearMenuOptions: PeriodOption[] = yearOptions.map((y) => ({ value: y, label: y }));
  const monthMenuOptions: PeriodOption[] = monthOptions.map((m) => ({
    value: m.value,
    label: formatReconMonthOnly(m.value),
  }));

  return (
    <div
      className={cn("app-period-picker", disabled && "pointer-events-none opacity-60")}
      data-testid={pickerTestId}
      role="group"
      aria-labelledby={`${groupId}-label`}
    >
      <span id={`${groupId}-label`} className="sr-only">
        Reporting period
      </span>

      <span className="app-period-picker-icon" aria-hidden>
        <CalendarDays className="h-4 w-4" strokeWidth={2} />
      </span>

      <PeriodMenu
        id={monthId}
        testId={monthTestId}
        ariaLabel="Select month"
        value={monthKey}
        displayValue={monthDisplay}
        options={monthMenuOptions}
        onChange={onMonthChange}
        open={openMenu === "month"}
        onOpenChange={(next) => setOpenMenu(next ? "month" : null)}
        disabled={disabled || monthOptions.length === 0}
        segmentClass="app-period-picker-month"
        menuMinWidth="10.5rem"
      />

      <PeriodMenu
        id={yearId}
        testId={yearTestId}
        ariaLabel="Select year"
        value={year}
        displayValue={year || "Year"}
        options={yearMenuOptions}
        onChange={onYearChange}
        open={openMenu === "year"}
        onOpenChange={(next) => setOpenMenu(next ? "year" : null)}
        disabled={disabled}
        segmentClass="app-period-picker-year"
        menuMinWidth="5.5rem"
      />
    </div>
  );
}
