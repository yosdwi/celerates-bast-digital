import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PayrollCycle } from "../api/payroll";
import * as exportApi from "../api/payrollExport";
import type { TalentOpsSession } from "../api/types";
import PayrollExportPanel from "./PayrollExportPanel";

vi.mock("../api/payrollExport", async () => {
  const actual = await vi.importActual<typeof import("../api/payrollExport")>("../api/payrollExport");
  return {
    ...actual,
    getPayrollExportHistory: vi.fn(),
    exportPayrollAttendance: vi.fn(),
  };
});

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const cycle: PayrollCycle = {
  cycle_id: "2026-09:2026-08-21:2026-09-20",
  label: "Payroll September 2026",
  year: 2026,
  month: 9,
  start: "2026-08-21",
  end: "2026-09-20",
};

beforeEach(() => {
  vi.mocked(exportApi.getPayrollExportHistory).mockResolvedValue({
    cycle_id: cycle.cycle_id,
    cycle_label: cycle.label,
    start_date: cycle.start,
    end_date: cycle.end,
    items: [],
  });
  vi.mocked(exportApi.exportPayrollAttendance).mockResolvedValue({
    blob: new Blob(["legacy,csv\n"], { type: "text/csv" }),
    filename: "Attendance_Celerates.csv",
    exportId: "export-1",
    rowCount: 12,
  });
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:payroll-export"),
    revokeObjectURL: vi.fn(),
  });
  HTMLAnchorElement.prototype.click = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("PayrollExportPanel", () => {
  it("shows the exact selected cycle before export and requires confirmation", async () => {
    render(<PayrollExportPanel session={session} cycle={cycle} />);

    expect(screen.getByText(/Payroll September 2026/)).toBeInTheDocument();
    expect(screen.getByText(/21 Agu 2026 – 20 Sep 2026/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    expect(screen.getByText("Konfirmasi export Developer")).toBeInTheDocument();
    expect(exportApi.exportPayrollAttendance).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Ya, export CSV" }));

    await waitFor(() => {
      expect(exportApi.exportPayrollAttendance).toHaveBeenCalledWith(
        "csrf-test",
        2026,
        9,
        "developer",
      );
    });
    expect(await screen.findByText(/Attendance_Celerates.csv · 12 baris/)).toBeInTheDocument();
  });

  it("renders metadata-only history for the cycle", async () => {
    vi.mocked(exportApi.getPayrollExportHistory).mockResolvedValue({
      cycle_id: cycle.cycle_id,
      cycle_label: cycle.label,
      start_date: cycle.start,
      end_date: cycle.end,
      items: [{
        export_id: "export-1",
        cycle_id: cycle.cycle_id,
        cycle_label: cycle.label,
        start_date: cycle.start,
        end_date: cycle.end,
        exported_at: "2026-09-20T05:00:00Z",
        exported_by: "pmo@example.com",
        report_type: "developer",
        role_filter: "Developer",
        employee_filter: null,
        filename: "Attendance_Celerates.csv",
        result: "SUCCESS",
        row_count: 12,
      }],
    });

    render(<PayrollExportPanel session={session} cycle={cycle} />);

    expect(await screen.findByText("Attendance_Celerates.csv")).toBeInTheDocument();
    expect(screen.getByText("Developer · 12 baris")).toBeInTheDocument();
    expect(screen.getByText("pmo@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Metadata saja/)).toBeInTheDocument();
  });
});
