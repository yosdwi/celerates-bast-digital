import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import SystemSyncPage from "./SystemSyncPage";

const session: TalentOpsSession = { user: { name: "PM Owner", role: "owner" }, csrf_token: "csrf-test", timezone: "Asia/Jakarta" };
const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 1, bast_ready: 1, need_attention: 0, open_tasks: 0, evidence_ready: 1 },
  attention: [], readiness: [], teams: [], delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] },
  sources: [{ source_key: "attendance", label: "PAMA Attendance", last_success_at: "2026-08-24T23:00:00Z", age_seconds: 120 }],
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("SystemSyncPage", () => {
  it("uses real health endpoints and labels source freshness as observation only", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "healthy" }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ready" }), { status: 200, headers: { "Content-Type": "application/json" } }));

    render(<SystemSyncPage session={session} data={data} onNavigate={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "System & Sync" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("healthy")).toBeInTheDocument());
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("PAMA Attendance")).toBeInTheDocument();
    expect(screen.getByText("Sync SLA")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });
});
