import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import TalentsPage from "./TalentsPage";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 1, bast_ready: 0, need_attention: 1, open_tasks: 0, evidence_ready: 0 },
  attention: [],
  readiness: [{
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
  }],
  teams: [],
  delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] },
  sources: [],
};

describe("TalentsPage", () => {
  it("renders directory facts and opens a talent by NRP", () => {
    const openTalent = vi.fn();
    render(
      <TalentsPage
        session={session}
        data={data}
        onNavigate={vi.fn()}
        onOpenTalent={openTalent}
      />,
    );

    expect(screen.getByRole("heading", { name: "Talents" })).toBeInTheDocument();
    expect(screen.getAllByText("Yoses Dwi Maheswara").length).toBeGreaterThan(0);
    expect(screen.getAllByText("JIMT24002").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByLabelText("Open Yoses Dwi Maheswara"));
    expect(openTalent).toHaveBeenCalledWith("JIMT24002");
  });
});
