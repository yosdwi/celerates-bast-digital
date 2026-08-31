export type TalentMobileTab = "attendance" | "tasks";

export interface TalentMobilePeriod {
  year: number;
  month: number;
  label: string;
}

export interface TalentMobileTask {
  task_key: string;
  title: string;
  work_date: string;
  task_source: string;
  evidence_count: number;
  complete: boolean;
}

export interface TalentMobileAttendanceItem {
  attendance_key: string;
  work_date: string;
  check_in: string | null;
  check_out: string | null;
  gap: "missing_clock_in" | "missing_clock_out" | "missing_both";
  evidence_count: number;
}

export interface TalentMobileAttendanceRequest {
  id: string;
  work_date: string;
  status: "pending" | "approved" | "rejected";
  label: string;
  rejection_reason: string | null;
}

export interface TalentMobileOverview {
  name: string;
  period: TalentMobilePeriod;
  task: {
    closed: number;
    complete: number;
    missing: number;
    items: TalentMobileTask[];
  };
  attendance: {
    total_work_days: number;
    needs_action: number;
    missing_data_days: string[];
    items: TalentMobileAttendanceItem[];
    requests: TalentMobileAttendanceRequest[];
  };
}

interface MutationResponse {
  status: "stored" | "submitted" | "already_present" | "already_open";
  message: string;
}

const BASE = "/api/talent/v1";
const TOKEN_KEY = "digital-bast-talent-mobile-token";

export class TalentMobileApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "TalentMobileApiError";
    this.status = status;
  }
}

export function captureTalentToken(): string | null {
  const url = new URL(window.location.href);
  const incoming = url.searchParams.get("t")?.trim() || null;
  if (incoming) {
    window.sessionStorage.setItem(TOKEN_KEY, incoming);
    url.searchParams.delete("t");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    return incoming;
  }
  return window.sessionStorage.getItem(TOKEN_KEY);
}

function currentToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = currentToken();
  if (!token) throw new TalentMobileApiError(401, "Link tidak tersedia. Buka ulang dari WhatsApp.");
  const response = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Proses gagal (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) message = payload.detail;
    } catch {
      // Keep the status based message for non-JSON errors.
    }
    throw new TalentMobileApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export function getTalentMobileOverview(): Promise<TalentMobileOverview> {
  return request<TalentMobileOverview>("/overview");
}

export function uploadTalentTaskEvidence(taskKey: string, file: File): Promise<MutationResponse> {
  const body = new FormData();
  body.set("file", file);
  return request<MutationResponse>(`/tasks/${encodeURIComponent(taskKey)}/evidence`, {
    method: "POST",
    body,
  });
}

export interface AttendanceResolutionInput {
  action: "worked" | "sakit" | "izin" | "cuti";
  checkIn?: string;
  checkOut?: string;
  file: File;
}

export function submitTalentAttendance(
  attendanceKey: string,
  input: AttendanceResolutionInput,
): Promise<MutationResponse> {
  const body = new FormData();
  body.set("action", input.action);
  if (input.checkIn) body.set("check_in", input.checkIn);
  if (input.checkOut) body.set("check_out", input.checkOut);
  body.set("file", input.file);
  return request<MutationResponse>(`/attendance/${encodeURIComponent(attendanceKey)}/resolution`, {
    method: "POST",
    body,
  });
}
