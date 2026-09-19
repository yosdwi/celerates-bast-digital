import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PayrollOverviewResponse } from "../api/payroll";
import type { TalentOpsSession } from "../api/types";
import PayrollPage from "./PayrollPage";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

function overview(): PayrollOverviewResponse {
  return {
    cycle: {
      cycle_id: "2026-09:2026-08-21:2026-09-20",
      label: "Payroll September 2026",
      year: 2026,
      month: 9,
      start: "2026-08-21",
      end: "2026-09-20",
    },
    evaluated_through: "2026-09-18",
    summary: {
      total_talents: 4,
      complete: 1,
      waiting_submitted: 1,
      needs_talent_action: 1,
      unverified: 1,
    },
    talents: [
      {
        employee_id: "a",
        nrp: "A01",
        name: "Andi",
        role: "Developer",
        status: "COMPLETE",
        evaluated_days: 20,
        complete_days: 20,
        waiting_days: 0,
        actionable_days: 0,
        unverified_days: 0,
        talent_action_required: false,
      },
      {
        employee_id: "b",
        nrp: "B01",
        name: "Budi",
        role: "Developer",
        status: "WAITING_SUBMITTED",
        evaluated_days: 20,
        complete_days: 18,
        waiting_days: 2,
        actionable_days: 0,
        unverified_days: 0,
        talent_action_required: false,
      },
      {
        employee_id: "c",
        nrp: "C01",
        name: "Citra",
        role: "IoT Operations",
        status: "NEEDS_TALENT_ACTION",
        evaluated_days: 19,
        complete_days: 18,
        waiting_days: 0,
        actionable_days: 1,
        unverified_days: 0,
        talent_action_required: true,
      },
      {
        employee_id: "d",
        nrp: "D01",
        name: "Dimas",
        role: "IoT Operations",
        status: "NEEDS_TALENT_ACTION",
        evaluated_days: 19,
        complete_days: 18,
        waiting_days: 0,
        actionable_days: 0,
        unverified_days: 1,
        talent_action_required: false,
      },
    ],
  };
}

afterEach(() => {
  cleanup();
});

describe("PayrollPage", () => {
  it("shows concise closing status and keeps unverified source separate from Talent action", () => {
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Payroll" })).toBeInTheDocument();
    expect(screen.getByText(/Payroll September 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Dievaluasi s.d. 18 Sep 2026/)).toBeInTheDocument();
    expect(screen.getByText("1 Talent perlu cek data sumber.")).toBeInTheDocument();

    const summary = screen.getByRole("region", { name: "Ringkasan Payroll" });
    expect(within(summary).getByText("Complete")).toBeInTheDocument();
    expect(within(summary).getByText("Perlu Talent")).toBeInTheDocument();
    expect(within(summary).getByText("Menunggu review")).toBeInTheDocument();
    expect(screen.getByLabelText("Review Queue")).toHaveTextContent("2");
    expect(screen.getByLabelText("Talent Follow-up")).toHaveTextContent("1");
  });

  it("filters the Talent list by status and global search", () => {
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    const filters = screen.getByRole("group", { name: "Filter status Payroll" });
    fireEvent.click(within(filters).getByRole("button", { name: "Perlu Talent" }));

    expect(screen.getAllByText("Citra").length).toBeGreaterThan(0);
    expect(screen.queryByText("Budi")).not.toBeInTheDocument();
    expect(screen.queryByText("Dimas")).not.toBeInTheDocument();

    fireEvent.click(within(filters).getByRole("button", { name: "Semua" }));
    fireEvent.change(screen.getByLabelText("Search talents"), { target: { value: "B01" } });

    expect(screen.getAllByText("Budi").length).toBeGreaterThan(0);
    expect(screen.queryByText("Citra")).not.toBeInTheDocument();
  });
});
