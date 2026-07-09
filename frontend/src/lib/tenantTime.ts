/**
 * Institution calendar dates — always use tenant timezone, not the browser clock.
 * Timestamps from the API stay UTC; this module is for business-day boundaries.
 */

export const DEFAULT_TENANT_TIMEZONE = "Asia/Singapore";
export const DEFAULT_TENANT_LOCALE = "en-SG";

type ZonedParts = { year: number; month: number; day: number };

function zonedParts(timeZone: string, at: Date = new Date()): ZonedParts {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(at);
  const read = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { year: read("year"), month: read("month"), day: read("day") };
}

/** YYYY-MM-DD in the institution timezone. */
export function tenantTodayIso(timeZone: string = DEFAULT_TENANT_TIMEZONE): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** YYYY-MM period key in the institution timezone. */
export function tenantMonthKey(
  timeZone: string = DEFAULT_TENANT_TIMEZONE,
  monthOffset = 0
): string {
  const { year, month } = zonedParts(timeZone);
  let y = year;
  let m = month - monthOffset;
  while (m <= 0) {
    m += 12;
    y -= 1;
  }
  while (m > 12) {
    m -= 12;
    y += 1;
  }
  return `${y}-${String(m).padStart(2, "0")}`;
}

/** First day of the current institution month as YYYY-MM-DD. */
export function tenantMonthStartIso(timeZone: string = DEFAULT_TENANT_TIMEZONE): string {
  return `${tenantMonthKey(timeZone)}-01`;
}

/** Shift a YYYY-MM-DD date-only string by N calendar days. */
export function shiftDateOnly(iso: string, days: number): string {
  const t = Date.parse(`${iso}T12:00:00Z`) + days * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

/** Whole days from institution today to a due date (negative = overdue). */
export function daysFromTenantToday(
  dateOnly: string,
  timeZone: string = DEFAULT_TENANT_TIMEZONE
): number {
  const today = tenantTodayIso(timeZone);
  const a = Date.parse(`${today}T00:00:00Z`);
  const b = Date.parse(`${dateOnly}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

export function isOverdueDate(
  dateOnly: string | null | undefined,
  timeZone: string = DEFAULT_TENANT_TIMEZONE
): boolean {
  if (!dateOnly) return false;
  return dateOnly < tenantTodayIso(timeZone);
}

export function isDueWithinDays(
  dateOnly: string | null | undefined,
  days: number,
  timeZone: string = DEFAULT_TENANT_TIMEZONE
): boolean {
  if (!dateOnly) return false;
  const delta = daysFromTenantToday(dateOnly, timeZone);
  return delta >= 0 && delta <= days;
}

export function tenantZonedParts(
  timeZone: string = DEFAULT_TENANT_TIMEZONE,
  at: Date = new Date()
): ZonedParts {
  return zonedParts(timeZone, at);
}

export function formatInTenantLocale(
  iso: string,
  timeZone: string,
  locale: string,
  options: Intl.DateTimeFormatOptions
): string {
  return new Date(iso).toLocaleString(locale, { timeZone, ...options });
}
