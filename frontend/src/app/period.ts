export interface PeriodSelection {
  year: number;
  month: number;
}

export function samePeriod(
  left: Pick<PeriodSelection, "year" | "month">,
  right: Pick<PeriodSelection, "year" | "month">,
): boolean {
  return left.year === right.year && left.month === right.month;
}

export function parsePeriodSearch(search: string): PeriodSelection | null {
  const params = new URLSearchParams(search);
  const rawYear = params.get("year");
  const rawMonth = params.get("month");
  if (rawYear === null || rawMonth === null) return null;

  const year = Number(rawYear);
  const month = Number(rawMonth);
  if (!Number.isInteger(year) || year <= 0) return null;
  if (!Number.isInteger(month) || month < 1 || month > 12) return null;
  return { year, month };
}

export function parseMonthInput(value: string): PeriodSelection | null {
  const match = value.match(/^(\d+)-(\d{2})$/);
  if (!match?.[1] || !match[2]) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!Number.isInteger(year) || year <= 0) return null;
  if (!Number.isInteger(month) || month < 1 || month > 12) return null;
  return { year, month };
}

export function monthInputValue(period: Pick<PeriodSelection, "year" | "month">): string {
  return `${String(period.year).padStart(4, "0")}-${String(period.month).padStart(2, "0")}`;
}

export function withPeriodQuery(
  pathname: string,
  search: string,
  period: Pick<PeriodSelection, "year" | "month">,
): string {
  const params = new URLSearchParams(search);
  params.set("year", String(period.year));
  params.set("month", String(period.month));
  const query = params.toString();
  return `${pathname}${query ? `?${query}` : ""}`;
}
