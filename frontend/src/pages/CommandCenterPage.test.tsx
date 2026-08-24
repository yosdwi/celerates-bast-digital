import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import CommandCenterPage from "./CommandCenterPage";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 2, bast_ready: 1, need_attention: 1, open_tasks: 3, evidence_ready: 1 },
  attention: [{ employee_id: "e1", nrp: "NRP001", name: "Alpha Talent", role: "Developer", overall_state: "incomplete", blockers: [{ domain: "evidence", state: "incomplete", issues: ["Evidence missing"] }] }],
  readiness: [
    { employee_id: "e1", nrp: "NRP001", name: "Alpha Talent", role: "Developer", overall_state: "incomplete", checks: { attendance: { state: "complete", issue_count: 0 }, timesheet: { state: "complete", issue_count: 0 }, task: { state: "complete", issue_count: 0 }, evidence: { state: "incomplete", issue_count: 1 } } },
    { employee_id: "e2", nrp: "NRP002", name: "Beta Talent", role: "IoT Operations", overall_state: "complete", checks: { attendance: { state: "complete", issue_count: 0 }, timesheet: { state: "complete", issue_count: 0 }, task: { state: "complete", issue_count: 0 }, evidence: { state: "complete", issue_count: 0 } } },
  ],
  teams: [
    { role: "Developer", total: 1, ready: 0, checks: { attendance_ready: 1, timesheet_ready: 1, task_ready: 1, evidence_ready: 0 } },
    { role: "IoT Operations", total: 1, ready: 1, checks: { attendance_ready: 1, timesheet_ready: 1, task_ready: 1, evidence_ready: 1 } },
  ],
  delivery: { total_tasks: 5, closed_tasks: 2, non_closed_tasks: 3, status_counts: [{ status: "Closed", count: 2 }, { status: "In Progress", count: 3 }] },
  sources: [{ source_key: "attendance", label: "PAMA Attendance", last_success_at: null, age_seconds: null }],
};

describe("CommandCenterPage", () => {
  it("renders values from the API contract and readiness states", () => {
    render(<CommandCenterPage session={session} data={data} refreshing={false} onRefresh={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Command Center" })).toBeInTheDocument();
    expect(screen.getAllByText("1 / 2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Alpha Talent").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getAllByText("3").length).toBeGreaterThan(0);
  });
});
