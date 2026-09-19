import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as payrollApi from "../api/payroll";
import type {
  PayrollCycle,
  PayrollReviewDecisionResponse,
  PayrollReviewQueueResponse,
} from "../api/payroll";
import type { TalentOpsSession } from "../api/types";
import PayrollReviewQueuePanel from "./PayrollReviewQueuePanel";

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-review",
  timezone: "Asia/Jakarta",
};

const cycle: PayrollCycle = {
  cycle_id: "2026-09:2026-08-21:2026-09-20",
  label: "Payroll September 2026",
  year: 2026,
  month: 9,
  start: "2026-08-21",
  end: "2026-09-20",
};

function queue(): PayrollReviewQueueResponse {
  return {
    cycle,
    summary: {
      total: 2,
      reviewable: 1,
      stale: 1,
      missing_clock_in: 0,
      missing_clock_out: 2,
      missing_both_worked: 0,
      absence: 0,
    },
    items: [
      {
        request_id: "00000000-0000-0000-0000-000000000101",
        attendance_id: 11,
        employee_id: "EMP-1",
        nrp: "10001",
        name: "Andi",
        role: "Developer",
        work_date: "2026-09-04",
        resolution_type: "missing_clock_out",
        raw_check_in: "07:30",
        raw_check_out: null,
        proposed_check_in: null,
        proposed_check_out: "17:40",
        absence_type: null,
        evidence_id: "00000000-0000-0000-0000-000000000201",
        evidence_content_type: "application/pdf",
        evidence_byte_size: 2048,
        evidence_caption: "Surat pendukung",
        evidence_uploaded_at: "2026-09-19T09:00:00Z",
        submitted_at: "2026-09-19T09:00:00Z",
        reviewable: true,
        reviewability_reason: null,
      },
      {
        request_id: "00000000-0000-0000-0000-000000000102",
        attendance_id: 12,
        employee_id: "EMP-2",
        nrp: "10002",
        name: "Budi",
        role: "Developer",
        work_date: "2026-09-07",
        resolution_type: "missing_clock_out",
        raw_check_in: "07:25",
        raw_check_out: "17:55",
        proposed_check_in: null,
        proposed_check_out: "17:40",
        absence_type: null,
        evidence_id: "00000000-0000-0000-0000-000000000202",
        evidence_content_type: "image/jpeg",
        evidence_byte_size: 1024,
        evidence_caption: "Foto evidence",
        evidence_uploaded_at: "2026-09-19T09:01:00Z",
        submitted_at: "2026-09-19T09:01:00Z",
        reviewable: false,
        reviewability_reason: "source_changed",
      },
    ],
  };
}

function result(overrides: Partial<PayrollReviewDecisionResponse> = {}): PayrollReviewDecisionResponse {
  return {
    requested: 1,
    succeeded: 1,
    skipped: 0,
    failed: 0,
    items: [{
      request_id: "00000000-0000-0000-0000-000000000101",
      status: "succeeded",
      outcome: "approved",
    }],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PayrollReviewQueuePanel", () => {
  it("keeps stale requests visible but not selectable and exposes existing evidence", async () => {
    vi.spyOn(payrollApi, "getPayrollReviewQueue").mockResolvedValue(queue());
    const onRefreshOverview = vi.fn(async () => undefined);

    render(
      <PayrollReviewQueuePanel
        session={session}
        cycle={cycle}
        onRefreshOverview={onRefreshOverview}
      />,
    );

    expect(await screen.findByText("Andi")).toBeInTheDocument();
    expect(screen.getByText("Budi")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Pilih pengajuan Andi/ })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: /Pilih pengajuan Budi/ })).toBeDisabled();
    expect(screen.getByText("Source attendance berubah")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Andi/ }));
    const detail = screen.getByLabelText("Detail review Andi");
    const evidence = within(detail).getByRole("link", { name: "Buka evidence" });
    expect(evidence).toHaveAttribute(
      "href",
      "/api/talentops/v1/attendance-resolutions/00000000-0000-0000-0000-000000000101/evidence",
    );
  });

  it("approves selected reviewable requests and refreshes authoritative projection", async () => {
    const getQueue = vi.spyOn(payrollApi, "getPayrollReviewQueue").mockResolvedValue(queue());
    const decide = vi.spyOn(payrollApi, "decidePayrollReviewQueue").mockResolvedValue(result());
    const onRefreshOverview = vi.fn(async () => undefined);

    render(
      <PayrollReviewQueuePanel
        session={session}
        cycle={cycle}
        onRefreshOverview={onRefreshOverview}
      />,
    );

    const checkbox = await screen.findByRole("checkbox", { name: /Pilih pengajuan Andi/ });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "Setujui" }));

    const dialog = screen.getByRole("dialog", { name: "Konfirmasi keputusan Payroll" });
    expect(within(dialog).getByText("Setujui 1 pengajuan?")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ya, setujui" }));

    await waitFor(() => {
      expect(decide).toHaveBeenCalledWith(
        "csrf-review",
        2026,
        9,
        ["00000000-0000-0000-0000-000000000101"],
        "approve",
        undefined,
      );
    });
    await waitFor(() => expect(onRefreshOverview).toHaveBeenCalledTimes(1));
    expect(getQueue).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Review selesai.")).toBeInTheDocument();
    expect(screen.getByText("1 berhasil")).toBeInTheDocument();
  });

  it("requires and submits a rejection reason", async () => {
    vi.spyOn(payrollApi, "getPayrollReviewQueue").mockResolvedValue(queue());
    const decide = vi.spyOn(payrollApi, "decidePayrollReviewQueue").mockResolvedValue(
      result({
        items: [{
          request_id: "00000000-0000-0000-0000-000000000101",
          status: "succeeded",
          outcome: "rejected",
        }],
      }),
    );

    render(
      <PayrollReviewQueuePanel
        session={session}
        cycle={cycle}
        onRefreshOverview={vi.fn(async () => undefined)}
      />,
    );

    fireEvent.click(await screen.findByRole("checkbox", { name: /Pilih pengajuan Andi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Tolak" }));

    const dialog = screen.getByRole("dialog", { name: "Konfirmasi keputusan Payroll" });
    fireEvent.change(within(dialog).getByLabelText("Alasan"), { target: { value: "Lainnya" } });
    expect(within(dialog).getByRole("button", { name: "Ya, tolak" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Detail alasan"), {
      target: { value: "Evidence perlu diperbaiki" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ya, tolak" }));

    await waitFor(() => {
      expect(decide).toHaveBeenCalledWith(
        "csrf-review",
        2026,
        9,
        ["00000000-0000-0000-0000-000000000101"],
        "reject",
        "Evidence perlu diperbaiki",
      );
    });
  });
});
