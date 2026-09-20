import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PayrollCycle } from "../api/payroll";
import * as payrollApi from "../api/payroll";
import type { TalentOpsSession } from "../api/types";
import PayrollFollowUpPanel from "./PayrollFollowUpPanel";

vi.mock("../api/payroll", async () => {
  const actual = await vi.importActual<typeof import("../api/payroll")>("../api/payroll");
  return {
    ...actual,
    getPayrollDigest: vi.fn(),
    previewPayrollReminder: vi.fn(),
    sendManualPayrollReminder: vi.fn(),
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
  vi.mocked(payrollApi.getPayrollDigest).mockResolvedValue({
    cycle,
    evaluated_through: "2026-09-20",
    summary: {
      total_talents: 1,
      complete: 0,
      waiting_submitted: 0,
      needs_talent_action: 1,
      unverified: 0,
      successful_reminder_deliveries: 0,
      successfully_reminded_talents: 0,
      unresponded_talents: 0,
      actionable_not_reminded: 1,
      delivery_retryable_failed: 0,
      delivery_final_failed: 0,
      delivery_unknown: 0,
    },
    items: [{
      employee_id: "EMP-1",
      nrp: "10001",
      name: "Talent One",
      role: "Developer",
      status: "NEEDS_TALENT_ACTION",
      actionable_days: 1,
      waiting_days: 0,
      unverified_days: 0,
      reason: "NOT_REMINDED",
      latest_delivery_state: null,
      latest_milestone: null,
      latest_sent_at: null,
      responded_at: null,
      error_code: null,
    }],
  });
  vi.mocked(payrollApi.previewPayrollReminder).mockResolvedValue({
    employee_id: "EMP-1",
    eligible: true,
    outcome: "eligible",
    actionable_days: 1,
    message: "Perbaiki attendance 19 Sep 2026\nPilih jenis koreksi lalu isi jam secara eksplisit.",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PayrollFollowUpPanel responsive surface", () => {
  it("keeps the follow-up list in the DOM without the desktop-only wrapper", async () => {
    const { container } = render(
      <PayrollFollowUpPanel session={session} cycle={cycle} onRefreshOverview={vi.fn()} />,
    );

    expect(await screen.findByText("Talent One")).toBeInTheDocument();
    expect(container.querySelector(".payroll-follow-up-table-wrap")).not.toBeNull();
    expect(container.querySelector(".desktop-table-wrap")).toBeNull();
  });

  it("wraps the WhatsApp reminder preview instead of using an unbounded pre block", async () => {
    const { container } = render(
      <PayrollFollowUpPanel session={session} cycle={cycle} onRefreshOverview={vi.fn()} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Preview reminder" }));

    await waitFor(() => {
      expect(payrollApi.previewPayrollReminder).toHaveBeenCalledWith("EMP-1", 2026, 9);
    });
    expect(container.querySelector("pre.payroll-follow-up-preview-message")).toHaveTextContent(
      "Perbaiki attendance 19 Sep 2026",
    );
  });
});
