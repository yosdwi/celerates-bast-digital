import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import BastReadinessPage from "./BastReadinessPage";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 2, bast_ready: 1, need_attention: 1, open_tasks: 0, evidence_ready: 1 },
  attention: [{
    employee_id: "internal-1",
    nrp: "JIMT24002",
    name: "Yoses Dwi Maheswara",
    role: "Developer",
    overall_state: "incomplete",
    blockers: [{ domain: "attendance", state: "incomplete", issues: ["Attendance missing clock-out"] }],
  }],
  readiness: [
    {
      employee_id: "internal-1",
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
    },
    {
      employee_id: "internal-2",
      nrp: "JIMT22012",
      name: "Ovianto",
      role: "Developer",
      overall_state: "complete",
      checks: {
        attendance: { state: "complete", issue_count: 0 },
        timesheet: { state: "complete", issue_count: 0 },
        task: { state: "complete", issue_count: 0 },
        evidence: { state: "complete", issue_count: 0 },
      },
    },
  ],
  teams: [],
  delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] },
  sources: [],
};

afterEach(() => cleanup());

describe("BastReadinessPage", () => {
  it("renders deterministic closing readiness and drills into Talent 360", () => {
    const openTalent = vi.fn();
    render(<BastReadinessPage session={session} data={data} onNavigate={vi.fn()} onOpenTalent={openTalent} />);

    expect(screen.getByRole("heading", { name: "BAST Readiness" })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getAllByText("Yoses Dwi Maheswara").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByLabelText("Open BAST readiness for Yoses Dwi Maheswara"));
    expect(screen.getByRole("heading", { name: "Yoses Dwi Maheswara" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Talent 360" }));
    expect(openTalent).toHaveBeenCalledWith("JIMT24002");
  });

  it("filters ready talents without inventing report generation state", () => {
    render(<BastReadinessPage session={session} data={data} onNavigate={vi.fn()} onOpenTalent={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Filter BAST readiness by state"), { target: { value: "complete" } });
    expect(screen.getAllByText("Ovianto").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Open BAST readiness for Yoses Dwi Maheswara")).not.toBeInTheDocument();
    expect(screen.queryByText("Generated")).not.toBeInTheDocument();
  });
});
