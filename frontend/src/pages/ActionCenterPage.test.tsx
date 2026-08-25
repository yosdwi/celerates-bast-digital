import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import ActionCenterPage from "./ActionCenterPage";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 2, bast_ready: 0, need_attention: 2, open_tasks: 1, evidence_ready: 1 },
  attention: [
    {
      employee_id: "internal-1",
      nrp: "JIMT24002",
      name: "Yoses Dwi Maheswara",
      role: "Developer",
      overall_state: "incomplete",
      blockers: [{ domain: "attendance", state: "incomplete", issues: ["Attendance missing clock-out on 2026-08-17"] }],
    },
    {
      employee_id: "internal-2",
      nrp: "JIMT25004",
      name: "Aris Purnomo",
      role: "Developer",
      overall_state: "needs_review",
      blockers: [{ domain: "evidence", state: "needs_review", issues: ["Closed task evidence needs review"] }],
    },
  ],
  readiness: [],
  teams: [],
  delivery: { total_tasks: 1, closed_tasks: 0, non_closed_tasks: 1, status_counts: [{ status: "Open", count: 1 }] },
  sources: [],
};

afterEach(() => cleanup());

describe("ActionCenterPage", () => {
  it("renders a grounded queue and opens Talent 360 by NRP", () => {
    const openTalent = vi.fn();
    render(<ActionCenterPage session={session} data={data} onNavigate={vi.fn()} onOpenTalent={openTalent} />);

    expect(screen.getByRole("heading", { name: "Action Center" })).toBeInTheDocument();
    expect(screen.getByText("Open actions")).toBeInTheDocument();
    expect(screen.getAllByText("Yoses Dwi Maheswara").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Attendance").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByLabelText("Open action for Yoses Dwi Maheswara"));
    expect(screen.getByRole("heading", { name: "Yoses Dwi Maheswara" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Talent 360" }));
    expect(openTalent).toHaveBeenCalledWith("JIMT24002");
  });

  it("filters the action queue without inventing acknowledgement state", () => {
    render(<ActionCenterPage session={session} data={data} onNavigate={vi.fn()} onOpenTalent={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Filter actions by state"), { target: { value: "needs_review" } });
    expect(screen.getAllByText("Aris Purnomo").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Open action for Yoses Dwi Maheswara")).not.toBeInTheDocument();
    expect(screen.queryByText("Acknowledged")).not.toBeInTheDocument();
  });
});
