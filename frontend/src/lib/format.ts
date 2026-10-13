const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
// Calendar dates ("2026-09-18") parse as UTC midnight; format them in UTC so no timezone shifts the day.
const calendarDate = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" });
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 0 });
const precisePercent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTime.format(new Date(iso)) : "—";
}

export function formatDate(isoDate: string | null | undefined): string {
  return isoDate ? calendarDate.format(new Date(isoDate)) : "—";
}

/** 0.381 -> "38%"; `precise` keeps one decimal for small values such as dividend yields. */
export function formatPercent(value: number | null | undefined, precise = false): string {
  if (value == null) return "—";
  return (precise ? precisePercent : percent).format(value);
}
