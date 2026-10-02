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

function whatsappStatus(changes: Record<string, unknown> = {}) {
  return {
    alive: true,
    ready: true,
    connection: "connected",
    me: "628111@c.us",
    qr_data_url: null,
    pairing_code: null,
    operator_action_required: false,
    operator_reason: null,
    connection_changed_at: "2026-09-20T00:00:00Z",
    recovery_state: "connected",
    recovery_reason: null,
    recovery_paused: false,
    last_probe_at: "2026-09-20T00:00:05Z",
    last_ready_at: "2026-09-20T00:00:05Z",
    last_ack_at: "2026-09-20T00:00:03Z",
    cooldown_until: null,
    recovery_attempts: 0,
    recovery_max_attempts: 3,
    recovery_policy_version: 1,
    applied_recovery_policy_version: 1,
    owner_acquired: true,
    owner_conflict_id: null,
    owner_conflict_heartbeat_at: null,
    storage_healthy: true,
    storage_reasons: [],
    free_bytes: 999999,
    free_inodes: 999,
    receipt_store_healthy: true,
    receipt_store_error: null,
    receipt_sent: 12,
    receipt_unknown: 0,
    receipt_in_flight: 0,
    transport: "whatsapp-web.js",
    ...changes,
  };
}

function installFetch(status = whatsappStatus()) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/health/live")) {
      return new Response(JSON.stringify({ status: "healthy" }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/health/ready")) {
      return new Response(JSON.stringify({ status: "ready" }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/system/whatsapp/operations")) {
      return new Response(JSON.stringify(status), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404, headers: { "Content-Type": "application/json" } });
  });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("SystemSyncPage", () => {
  it("uses real health endpoints and keeps source freshness observation semantics", async () => {
    installFetch();

    render(<SystemSyncPage session={session} data={data} onNavigate={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "System & Sync" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("healthy")).toBeInTheDocument());
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("PAMA Attendance")).toBeInTheDocument();
    expect(screen.getByText("Sync SLA")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Terhubung")).toBeInTheDocument());
    expect(screen.getByText("Single owner acquired")).toBeInTheDocument();
    expect(screen.getByText(/Sent 12 · UNKNOWN 0/)).toBeInTheDocument();
  });

  it("shows operator action instead of silently offering reconnect for a permanent logout", async () => {
    installFetch(whatsappStatus({
      ready: false,
      connection: "pairing-required",
      operator_action_required: true,
      operator_reason: "logged-out: LOGOUT",
      recovery_state: "operator_action_required",
      recovery_reason: "logged-out: LOGOUT",
      qr_data_url: "data:image/png;base64,test",
    }));

    render(<SystemSyncPage session={session} data={data} onNavigate={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Perlu tindakan")).toBeInTheDocument());
    expect(screen.getByText("logged-out: LOGOUT")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect aman" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mulai pairing" })).toBeInTheDocument();
    expect(screen.getByAltText("QR pairing WhatsApp")).toBeInTheDocument();
  });
});
