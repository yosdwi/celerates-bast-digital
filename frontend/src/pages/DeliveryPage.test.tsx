import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import DeliveryPage from "./DeliveryPage";

const session: TalentOpsSession = { user: { name: "PM Owner", role: "owner" }, csrf_token: "csrf-test", timezone: "Asia/Jakarta" };
const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 2, bast_ready: 1, need_attention: 1, open_tasks: 2, evidence_ready: 1 },
  attention: [{ employee_id: "e1", nrp: "JIMT24002", name: "Yoses Dwi Maheswara", role: "Developer", overall_state: "incomplete", blockers: [{ domain: "task", state: "incomplete", issues: ["2 tasks are not Closed"] }] }],
  readiness: [],
  teams: [{ role: "Developer", total: 2, ready: 1, checks: { attendance_ready: 2, timesheet_ready: 2, task_ready: 1, evidence_ready: 2 } }],
  delivery: { total_tasks: 5, closed_tasks: 3, non_closed_tasks: 2, status_counts: [{ status: "Closed", count: 3 }, { status: "Open", count: 2 }] },
  sources: [],
};

afterEach(() => cleanup());

describe("DeliveryPage", () => {
  it("renders only supported delivery facts and drills into task blockers", () => {
    const openTalent = vi.fn();
    render(<DeliveryPage session={session} data={data} onNavigate={vi.fn()} onOpenTalent={openTalent} />);
    expect(screen.getByRole("heading", { name: "Delivery" })).toBeInTheDocument();
    expect(screen.getAllByText("Closed").length).toBeGreaterThan(0);
    expect(screen.getByText("No closure trend is inferred.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Open task blocker for Yoses Dwi Maheswara"));
    fireEvent.click(screen.getByRole("button", { name: "Open Talent 360" }));
    expect(openTalent).toHaveBeenCalledWith("JIMT24002");
  });
});
