import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decidePayrollReviewQueue,
  getPayrollCycles,
  getPayrollOverview,
  getPayrollReviewQueue,
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

  it("loads the review queue for the selected payroll cycle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], summary: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await getPayrollReviewQueue(2026, 9);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/talentops/v1/payroll/review-queue?year=2026&month=9",
    );
  });

  it("sends csrf, exact ids, decision, and structured rejection reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      requested: 2,
      succeeded: 1,
      skipped: 1,
      failed: 0,
      items: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    await decidePayrollReviewQueue(
      "csrf-1",
      2026,
      9,
      ["request-1", "request-2"],
      "reject",
      "  Evidence tidak cukup jelas  ",
    );

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(
      "/api/talentops/v1/payroll/review-queue/decide?year=2026&month=9",
    );
    expect(init).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({
        "X-CSRF-Token": "csrf-1",
        "Content-Type": "application/json",
      }),
    });
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      request_ids: ["request-1", "request-2"],
      decision: "reject",
      rejection_reason: "Evidence tidak cukup jelas",
    });
  });
});
