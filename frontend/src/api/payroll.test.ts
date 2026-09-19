import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getPayrollCycles,
  getPayrollOverview,
  getPayrollTalentDetail,
} from "./payroll";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Payroll API client", () => {
  it("uses the independent payroll cycle and overview endpoints", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ current_cycle_id: "cycle", cycles: [] }))
      .mockResolvedValueOnce(jsonResponse({ cycle: {}, summary: {}, talents: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getPayrollCycles();
    await getPayrollOverview(2026, 9);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/talentops/v1/payroll/cycles");
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/talentops/v1/payroll/overview?year=2026&month=9",
    );
  });

  it("encodes the Talent identity in the detail route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ days: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getPayrollTalentDetail("employee/a b", 2026, 9);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/talentops/v1/payroll/talents/employee%2Fa%20b?year=2026&month=9",
    );
  });
});
