import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AttendanceGapMutationResponse, AttendanceGapsResponse } from "../api/types";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import AttendanceGapsPage from "./AttendanceGapsPage";

const getAttendanceGaps = vi.fn<(year?: number, month?: number) => Promise<AttendanceGapsResponse>>();
const submitAttendanceGap = vi.fn<(...args: unknown[]) => Promise<AttendanceGapMutationResponse>>();

vi.mock("../api/talentops", () => ({
  getAttendanceGaps: (...args: [number?, number?]) => getAttendanceGaps(...args),
  submitAttendanceGap: (...args: unknown[]) => submitAttendanceGap(...args),
}));

const session: TalentOpsSession = {
  user: { name: "PM Owner", role: "owner" },
  csrf_token: "csrf-test",
  timezone: "Asia/Jakarta",
};

const data: CommandCenterResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  summary: { active_talents: 2, bast_ready: 0, need_attention: 1, open_tasks: 0, evidence_ready: 0 },
  attention: [],
  readiness: [],
  teams: [],
  delivery: { total_tasks: 0, closed_tasks: 0, non_closed_tasks: 0, status_counts: [] },
  sources: [],
};

const gapsResponse: AttendanceGapsResponse = {
  period: { year: 2026, month: 8, start: "2026-08-01", end: "2026-08-31", label: "1-31 Agustus 2026" },
  items: [
    {
      employee_id: "internal-1",
      name: "Bayu Sutra",
      attendance_key: "attendance-key-1",
      work_date: "2026-08-24",
      check_in: null,
      check_out: null,
      gap: "missing_both",
      evidence_count: 0,
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AttendanceGapsPage", () => {
  it("lists gaps across talents and submits an absence resolution with optional clock values", async () => {
    getAttendanceGaps.mockResolvedValue(gapsResponse);
    submitAttendanceGap.mockResolvedValue({ status: "applied", message: "Attendance sudah diperbarui" });

    const { container } = render(<AttendanceGapsPage session={session} data={data} onNavigate={vi.fn()} />);

    await waitFor(() => expect(screen.getAllByText("Bayu Sutra").length).toBeGreaterThan(0));
    expect(getAttendanceGaps).toHaveBeenCalledWith(2026, 8);

    const table = container.querySelector(".desktop-table-wrap") as HTMLElement;
    fireEvent.click(within(table).getByRole("button", { name: "Upload + Isi" }));
    fireEvent.click(within(table).getByRole("button", { name: "Izin" }));

    const file = new File(["evidence"], "evidence.jpg", { type: "image/jpeg" });
    const fileInput = within(table).getByLabelText("+ Tambah Foto Evidence") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(within(table).getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(submitAttendanceGap).toHaveBeenCalled());
    expect(submitAttendanceGap).toHaveBeenCalledWith(
      "csrf-test",
      "internal-1",
      "attendance-key-1",
      { year: 2026, month: 8 },
      expect.objectContaining({ action: "izin", file }),
    );
  });
});
