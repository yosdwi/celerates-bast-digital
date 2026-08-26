import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import App from "./App";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

function dataFor(year: number, month: number): CommandCenterResponse {
  const monthText = String(month).padStart(2, "0");
  return {
    period: {
      year,
      month,
      start: `${year}-${monthText}-01`,
      end: `${year}-${monthText}-28`,
      label: `${monthText}/${year}`,
    },
    summary: {
      active_talents: 1,
      bast_ready: 1,
      need_attention: 0,
      open_tasks: 0,
      evidence_ready: 1,
    },
    attention: [],
    readiness: [{
      employee_id: "e1",
      nrp: "NRP001",
      name: "Alpha Talent",
      role: "Developer",
      overall_state: "complete",
      checks: {
        attendance: { state: "complete", issue_count: 0 },
        timesheet: { state: "complete", issue_count: 0 },
        task: { state: "complete", issue_count: 0 },
        evidence: { state: "complete", issue_count: 0 },
      },
    }],
    teams: [{
      role: "Developer",
      total: 1,
      ready: 1,
      checks: {
        attendance_ready: 1,
        timesheet_ready: 1,
        task_ready: 1,
        evidence_ready: 1,
      },
    }],
    delivery: {
      total_tasks: 0,
      closed_tasks: 0,
      non_closed_tasks: 0,
      status_counts: [],
    },
    sources: [],
    signals: [],
  };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/admin/talentops/?year=2026&month=7");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App global period", () => {
  it("boots from the URL and keeps the selected month in global navigation state", async () => {
    vi.spyOn(api, "getSession").mockResolvedValue(session);
    const getCommandCenter = vi
      .spyOn(api, "getCommandCenter")
      .mockImplementation(async (year?: number, month?: number) => dataFor(year ?? 2026, month ?? 8));

    render(<App />);

    await waitFor(() => {
      expect(getCommandCenter).toHaveBeenCalledWith(2026, 7);
    });

    const periodInput = await screen.findByLabelText("Reporting period");
    expect(periodInput).toHaveValue("2026-07");
    expect(window.location.search).toContain("year=2026");
    expect(window.location.search).toContain("month=7");

    fireEvent.change(periodInput, { target: { value: "2026-08" } });

    await waitFor(() => {
      expect(getCommandCenter).toHaveBeenCalledWith(2026, 8);
      expect(screen.getByLabelText("Reporting period")).toHaveValue("2026-08");
    });
    expect(window.location.search).toContain("month=8");
  });
});
