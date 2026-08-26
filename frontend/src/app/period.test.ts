import { describe, expect, it } from "vitest";
import {
  monthInputValue,
  parseMonthInput,
  parsePeriodSearch,
  samePeriod,
  withPeriodQuery,
} from "./period";

describe("period helpers", () => {
  it("parses a valid reporting period from URL search params", () => {
    expect(parsePeriodSearch("?year=2026&month=8")).toEqual({ year: 2026, month: 8 });
  });

  it("rejects incomplete or invalid URL periods", () => {
    expect(parsePeriodSearch("?year=2026")).toBeNull();
    expect(parsePeriodSearch("?year=2026&month=13")).toBeNull();
    expect(parsePeriodSearch("?year=nope&month=8")).toBeNull();
  });

  it("converts native month input values without changing the period", () => {
    const period = parseMonthInput("2026-08");
    expect(period).toEqual({ year: 2026, month: 8 });
    expect(period && monthInputValue(period)).toBe("2026-08");
    expect(parseMonthInput("2026-00")).toBeNull();
  });

  it("preserves unrelated query parameters while changing period", () => {
    expect(withPeriodQuery(
      "/admin/talentops/talents",
      "?view=compact&year=2026&month=7",
      { year: 2026, month: 8 },
    )).toBe("/admin/talentops/talents?view=compact&year=2026&month=8");
  });

  it("compares periods by year and month", () => {
    expect(samePeriod({ year: 2026, month: 8 }, { year: 2026, month: 8 })).toBe(true);
    expect(samePeriod({ year: 2026, month: 8 }, { year: 2026, month: 7 })).toBe(false);
  });
});
