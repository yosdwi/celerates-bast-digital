import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import SettingsPage from "./SettingsPage";

const session: TalentOpsSession = { user: { name: "PM Owner", role: "owner" }, csrf_token: "csrf-test", timezone: "Asia/Jakarta" };
const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 1, bast_ready: 1, need_attention: 0, open_tasks: 0, evidence_ready: 1 },
  attention: [], readiness: [], teams: [], delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] }, sources: [],
};

afterEach(() => cleanup());

describe("SettingsPage", () => {
  it("shows real workflow controls and the authorization boundary", () => {
    render(<SettingsPage session={session} data={data} onNavigate={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Asia/Jakarta")).toBeInTheDocument();
    expect(screen.getByText("Data Workspace")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "WhatsApp reminders" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "PMO access" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Provision PMO" })).toBeInTheDocument();
    expect(screen.getByText(/Admin provisions PMO access/)).toBeInTheDocument();
  });
});
