import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as payrollApi from "../api/payroll";
import type {
  PayrollOverviewResponse,
  PayrollReviewQueueResponse,
  PayrollTalentDetailResponse,
} from "../api/payroll";
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

function emptyQueue(): PayrollReviewQueueResponse {
  const data = overview();
  return {
    cycle: data.cycle,
    summary: {
      total: 0,
      reviewable: 0,
      stale: 0,
      missing_clock_in: 0,
      missing_clock_out: 0,
      missing_both_worked: 0,
      absence: 0,
    },
    items: [],
  };
}

function detailFor(employeeId: string): PayrollTalentDetailResponse {
  const base = overview();
  if (employeeId === "c") {
    return {
      ...base.talents[2],
      cycle: base.cycle,
      evaluated_through: base.evaluated_through,
      days: [{
        attendance_id: 17,
        attendance_key: "17",
        work_date: "2026-09-07",
        schedule_state: "WORKING",
        source_state: "AVAILABLE",
        raw_check_in: null,
        raw_check_out: "2026-09-07T17:52:00+07:00",
        proposed_check_in: "2026-09-07T07:31:00+07:00",
        proposed_check_out: null,
        resolution_id: "resolution-c",
        resolution_status: "rejected",
        resolution_type: "missing_clock_in",
        absence_type: null,
        rejection_reason: "Jam masuk tidak sesuai bukti",
        has_evidence: true,
        status: "NEEDS_TALENT_ACTION",
        reason: "CORRECTION_REJECTED",
        talent_action_required: true,
      }],
    };
  }

  return {
    ...base.talents[1],
    cycle: base.cycle,
    evaluated_through: base.evaluated_through,
    days: [
      {
        attendance_id: 14,
        attendance_key: "14",
        work_date: "2026-09-04",
        schedule_state: "WORKING",
        source_state: "AVAILABLE",
        raw_check_in: "2026-09-04T07:32:00+07:00",
        raw_check_out: null,
        proposed_check_in: null,
        proposed_check_out: "2026-09-04T17:40:00+07:00",
        resolution_id: "resolution-b",
        resolution_status: "pending",
        resolution_type: "missing_clock_out",
        absence_type: null,
        rejection_reason: null,
        has_evidence: true,
        status: "WAITING_SUBMITTED",
        reason: "GAP_COVERED_BY_SUBMITTED_REQUEST",
        talent_action_required: false,
      },
      {
        attendance_id: 15,
        attendance_key: "15",
        work_date: "2026-09-05",
        schedule_state: "WORKING",
        source_state: "AVAILABLE",
        raw_check_in: "2026-09-05T07:29:00+07:00",
        raw_check_out: "2026-09-05T17:38:00+07:00",
        proposed_check_in: null,
        proposed_check_out: null,
        resolution_id: null,
        resolution_status: null,
        resolution_type: null,
        absence_type: null,
        rejection_reason: null,
        has_evidence: false,
        status: "COMPLETE",
        reason: "RAW_COMPLETE",
        talent_action_required: false,
      },
    ],
  };
}

beforeEach(() => {
  vi.spyOn(payrollApi, "getPayrollOverview").mockImplementation(async () => overview());
  vi.spyOn(payrollApi, "getPayrollReviewQueue").mockImplementation(async () => emptyQueue());
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PayrollPage", () => {
  it("shows concise closing status and keeps unverified source separate from Talent action", () => {
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    const heading = screen.getByRole("heading", { name: "Payroll" });
    expect(heading).toBeInTheDocument();
    // The export panel further down the page repeats the same cycle label
    // for its own confirmation line, so scope to the page-heading block
    // rather than screen-wide getByText.
    const headingBlock = heading.closest(".payroll-heading") as HTMLElement;
    expect(within(headingBlock).getByText(/Payroll September 2026/)).toBeInTheDocument();
    expect(within(headingBlock).getByText(/Dievaluasi s.d. 18 Sep 2026/)).toBeInTheDocument();
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
    // WorkspaceFrame's mobile search-toggle button shares the same
    // aria-label as the actual search input; the textbox role disambiguates.
    fireEvent.change(screen.getByRole("textbox", { name: "Search talents" }), {
      target: { value: "B01" },
    });

    expect(screen.getAllByText("Budi").length).toBeGreaterThan(0);
    expect(screen.queryByText("Citra")).not.toBeInTheDocument();
  });

  it("loads attendance detail on demand and shows actual, proposed and evidence facts", async () => {
    const getDetail = vi
      .spyOn(payrollApi, "getPayrollTalentDetail")
      .mockImplementation(async (employeeId) => detailFor(employeeId));
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    expect(getDetail).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Lihat detail Budi" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Detail attendance Budi" });
    await waitFor(() => expect(getDetail).toHaveBeenCalledWith("b", 2026, 9));
    expect(within(dialog).getByText("4 Sep 2026")).toBeInTheDocument();
    expect(within(dialog).getByText("Pulang 17:40")).toBeInTheDocument();
    // The dialog lists one day-card per attendance day, each with its own
    // "Evidence:"/"Review:" line, so scope to this day's card specifically.
    const dayCard = within(dialog).getByText("4 Sep 2026").closest("article") as HTMLElement;
    expect(within(dayCard).getByText("Evidence:").parentElement).toHaveTextContent("Ada");
    expect(within(dayCard).getByText("Review:").parentElement).toHaveTextContent("pending");

    fireEvent.click(within(dialog).getByRole("button", { name: "Tutup detail" }));
    expect(screen.queryByRole("dialog", { name: "Detail attendance Budi" })).not.toBeInTheDocument();
  });

  it("lets the operator pick a different Payroll cycle", () => {
    const onPeriodChange = vi.fn();
    render(
      <PayrollPage
        session={session}
        data={overview()}
        onNavigate={vi.fn()}
        onPeriodChange={onPeriodChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Payroll cycle"), {
      target: { value: "2026-08" },
    });

    expect(onPeriodChange).toHaveBeenCalledWith({ year: 2026, month: 8 });
  });

  it("hides the cycle picker when no onPeriodChange handler is provided", () => {
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    expect(screen.queryByLabelText("Payroll cycle")).not.toBeInTheDocument();
  });

  it("shows rejection context without turning the drawer into an approval surface", async () => {
    vi.spyOn(payrollApi, "getPayrollTalentDetail")
      .mockImplementation(async (employeeId) => detailFor(employeeId));
    render(<PayrollPage session={session} data={overview()} onNavigate={vi.fn()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "Lihat detail Citra" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Detail attendance Citra" });
    expect(within(dialog).getByText("Pengajuan sebelumnya ditolak")).toBeInTheDocument();
    expect(within(dialog).getByText(/Jam masuk tidak sesuai bukti/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /setujui/i })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /tolak/i })).not.toBeInTheDocument();
  });
});
