import { afterEach, describe, expect, it, vi } from "vitest";
import {
  exportPayrollAttendance,
  getPayrollExportHistory,
} from "./payrollExport";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Payroll export API client", () => {
  it("loads metadata history for the selected payroll cycle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getPayrollExportHistory(2026, 9);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/talentops/v1/payroll/exports/history?year=2026&month=9",
    );
  });

  it("posts the selected report with csrf and returns download metadata", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("legacy,csv\n", {
      status: 200,
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=Attendance_Celerates.csv",
        "X-Payroll-Export-Id": "export-1",
        "X-Payroll-Row-Count": "23",
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await exportPayrollAttendance("csrf-1", 2026, 9, "shifting");

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/talentops/v1/payroll/exports?year=2026&month=9");
    expect(init).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({
        "X-CSRF-Token": "csrf-1",
        "Content-Type": "application/json",
      }),
    });
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ report_type: "shifting" });
    expect(result.filename).toBe("Attendance_Celerates.csv");
    expect(result.exportId).toBe("export-1");
    expect(result.rowCount).toBe(23);
    expect(await result.blob.text()).toBe("legacy,csv\n");
  });
});
