import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentDetailResponse, TalentOpsSession } from "../api/types";
import Talent360Page from "./Talent360Page";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const commandCenter: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 1, bast_ready: 0, need_attention: 1, open_tasks: 0, evidence_ready: 1 },
  attention: [],
  readiness: [],
  teams: [],
  delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] },
  sources: [],
};

const talent: TalentDetailResponse = {
  period: commandCenter.period,
  nrp: "JIMT24002",
  name: "Yoses Dwi Maheswara",
  role: "Developer",
  overall_state: "incomplete",
  checks: {
    attendance: { state: "incomplete", issue_count: 1 },
    timesheet: { state: "incomplete", issue_count: 1 },
    task: { state: "complete", issue_count: 0 },
    evidence: { state: "complete", issue_count: 0 },
  },
  blockers: [{ domain: "attendance", state: "incomplete", issues: ["Attendance missing"] }],
  attendance_days: [{
    work_date: "2026-08-01",
    is_off: false,
    has_record: false,
    has_clock_in: false,
    has_clock_out: false,
    has_evidence: false,
    state: "incomplete",
  }],
  timesheet_days: [{
    work_date: "2026-08-01",
    is_off: false,
    has_record: false,
    has_remarks: false,
    blocked_by_attendance: true,
    state: "incomplete",
  }],
  tasks: [{
    work_date: "2026-08-01",
    title: "Closed task",
    status: "Closed",
    evidence_count: 1,
    is_closed: true,
    evidence_ready: true,
  }],
  availability: { attendance: true, evidence: true },
};

describe("Talent360Page", () => {
  it("renders identity and deterministic readiness facts", () => {
    render(
      <Talent360Page
        session={session}
        commandCenter={commandCenter}
        talent={talent}
        onNavigate={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Yoses Dwi Maheswara" })).toBeInTheDocument();
    expect(screen.getByText(/JIMT24002/)).toBeInTheDocument();
    expect(screen.getByText("Attendance missing")).toBeInTheDocument();
    expect(screen.getByText("Blocked by attendance validation")).toBeInTheDocument();
    expect(screen.getAllByText("Closed task").length).toBeGreaterThan(0);
  });
});
