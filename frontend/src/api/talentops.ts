import { ApiError, apiFetch, apiFetchResponse } from "./client";
import type {
  AiResponse,
  AttendanceGapMutationResponse,
  AttendanceGapsResponse,
  AttendanceResolution,
  BastReadiness,
  CommandCenterResponse,
  FollowUpDraft,
  FollowUpSendResponse,
  FollowUpSource,
  IdentityRebindRequest,
  NotificationSettings,
  PeriodView,
  TalentDetailResponse,
  TalentMobileSettings,
  TalentOpsSession,
  TaskEvidencePage,
  WhatsAppInvite,
  WhatsAppStatus,
  WorkflowOperator,
  WorkflowOperatorInput,
} from "./types";

const BASE = "/api/talentops/v1";

export type BastReportType = "developer" | "iotoperation";
export type BastGenerationMode = "preview" | "final";

export interface GeneratedBastFile {
  blob: Blob;
  filename: string;
}

export type BastJobStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";
export type BastJobDisplayStatus = BastJobStatus | "stale";

export interface BastGenerationJob {
  id: string;
  status: BastJobStatus;
  display_status: BastJobDisplayStatus;
  report_type: BastReportType;
  year: number;
  month: number;
  mode: BastGenerationMode;
  forced: boolean;
  force_reason: string | null;
  requested_by: string;
  artifact_name: string | null;
  fingerprint: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export function getSession(): Promise<TalentOpsSession> {
  return apiFetch<TalentOpsSession>(`${BASE}/session`);
}

export function getWhatsAppStatus(): Promise<WhatsAppStatus> {
  return apiFetch<WhatsAppStatus>(`${BASE}/system/whatsapp`);
}

export function getCommandCenter(year?: number, month?: number): Promise<CommandCenterResponse> {
  const query = year !== undefined && month !== undefined ? `?year=${year}&month=${month}` : "";
  return apiFetch<CommandCenterResponse>(`${BASE}/command-center${query}`);
}

export function getTalentDetail(nrp: string, year: number, month: number): Promise<TalentDetailResponse> {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiFetch<TalentDetailResponse>(`${BASE}/talents/${encodeURIComponent(nrp)}?${query.toString()}`);
}

export function getTaskEvidence(
  period: Pick<PeriodView, "year" | "month">,
  options: { nrp?: string; limit?: number; offset?: number } = {},
): Promise<TaskEvidencePage> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    limit: String(options.limit ?? 60),
    offset: String(options.offset ?? 0),
  });
  if (options.nrp?.trim()) query.set("nrp", options.nrp.trim());
  return apiFetch<TaskEvidencePage>(`${BASE}/task-evidence?${query.toString()}`);
}

export function getAttendanceResolutions(): Promise<AttendanceResolution[]> {
  return apiFetch<AttendanceResolution[]>(`${BASE}/attendance-resolutions`);
}

export function attendanceResolutionEvidenceUrl(requestId: string): string {
  return `${BASE}/attendance-resolutions/${encodeURIComponent(requestId)}/evidence`;
}

export function approveAttendanceResolution(csrfToken: string, requestId: string): Promise<{ status: "approved" }> {
  return apiFetch<{ status: "approved" }>(
    `${BASE}/attendance-resolutions/${encodeURIComponent(requestId)}/approve`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}

export function rejectAttendanceResolution(
  csrfToken: string,
  requestId: string,
  reason: string,
): Promise<{ status: "rejected" }> {
  return apiFetch<{ status: "rejected" }>(
    `${BASE}/attendance-resolutions/${encodeURIComponent(requestId)}/reject`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ reason }),
    },
  );
}

export function getIdentityRebinds(): Promise<IdentityRebindRequest[]> {
  return apiFetch<IdentityRebindRequest[]>(`${BASE}/identity-rebinds`);
}

export function approveIdentityRebind(csrfToken: string, requestId: string): Promise<{ status: "approved" }> {
  return apiFetch<{ status: "approved" }>(
    `${BASE}/identity-rebinds/${encodeURIComponent(requestId)}/approve`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}

export function rejectIdentityRebind(
  csrfToken: string,
  requestId: string,
  reason: string,
): Promise<{ status: "rejected" }> {
  return apiFetch<{ status: "rejected" }>(
    `${BASE}/identity-rebinds/${encodeURIComponent(requestId)}/reject`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ reason }),
    },
  );
}

export function getWorkflowOperators(): Promise<WorkflowOperator[]> {
  return apiFetch<WorkflowOperator[]>(`${BASE}/operators`);
}

export function saveWorkflowOperator(
  csrfToken: string,
  email: string,
  input: WorkflowOperatorInput,
): Promise<WorkflowOperator> {
  return apiFetch<WorkflowOperator>(`${BASE}/operators/${encodeURIComponent(email)}`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  });
}

export function issueWorkflowOperatorInvite(csrfToken: string, email: string): Promise<WhatsAppInvite> {
  return apiFetch<WhatsAppInvite>(
    `${BASE}/operators/${encodeURIComponent(email)}/whatsapp-invite`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}

export function unlinkWorkflowOperatorWhatsApp(
  csrfToken: string,
  email: string,
): Promise<{ removed: boolean }> {
  return apiFetch<{ removed: boolean }>(`${BASE}/operators/${encodeURIComponent(email)}/whatsapp`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

export function getNotificationSettings(scopeKey = "default"): Promise<NotificationSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<NotificationSettings>(`${BASE}/notification-settings?${query.toString()}`);
}

export function saveNotificationSettings(
  csrfToken: string,
  input: Omit<NotificationSettings, "scope_key">,
  scopeKey = "default",
): Promise<NotificationSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<NotificationSettings>(`${BASE}/notification-settings?${query.toString()}`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  });
}

export function getTalentMobileSettings(scopeKey = "default"): Promise<TalentMobileSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<TalentMobileSettings>(`${BASE}/talent-mobile-settings?${query.toString()}`);
}

export function saveTalentMobileSettings(
  csrfToken: string,
  publicUrl: string | null,
  scopeKey = "default",
): Promise<TalentMobileSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<TalentMobileSettings>(`${BASE}/talent-mobile-settings?${query.toString()}`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ public_url: publicUrl }),
  });
}

export function getBastReadiness(
  period: Pick<PeriodView, "year" | "month">,
  reportType: BastReportType,
): Promise<BastReadiness> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    report_type: reportType,
  });
  return apiFetch<BastReadiness>(`${BASE}/bast/readiness?${query.toString()}`);
}

export function askCommandCenter(
  csrfToken: string,
  question: string,
  period: Pick<PeriodView, "year" | "month">,
): Promise<AiResponse> {
  return apiFetch<AiResponse>(`${BASE}/ai/command-center`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ year: period.year, month: period.month, question }),
  });
}

export function askTalent(
  csrfToken: string,
  nrp: string,
  question: string,
  period: Pick<PeriodView, "year" | "month">,
): Promise<AiResponse> {
  return apiFetch<AiResponse>(`${BASE}/ai/talents/${encodeURIComponent(nrp)}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ year: period.year, month: period.month, question }),
  });
}

export function createBastGenerationJob(
  csrfToken: string,
  period: Pick<PeriodView, "year" | "month">,
  reportType: BastReportType,
  mode: BastGenerationMode = "final",
  force = false,
  forceReason = "",
): Promise<BastGenerationJob> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    report_type: reportType,
    mode,
    force: String(force),
  });
  if (forceReason.trim()) query.set("force_reason", forceReason.trim());
  return apiFetch<BastGenerationJob>(`${BASE}/bast/generate?${query.toString()}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

export function getBastGenerationJob(jobId: string): Promise<BastGenerationJob> {
  return apiFetch<BastGenerationJob>(`${BASE}/bast/generate/jobs/${encodeURIComponent(jobId)}`);
}

export function listBastGenerationJobs(limit = 20): Promise<BastGenerationJob[]> {
  return apiFetch<BastGenerationJob[]>(`${BASE}/bast/generate/jobs?limit=${limit}`);
}

export async function downloadBastDocument(
  period: Pick<PeriodView, "year" | "month">,
  reportType: BastReportType,
): Promise<GeneratedBastFile> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    report_type: reportType,
  });
  const response = await apiFetchResponse(`${BASE}/bast/generate/download?${query.toString()}`, {
    headers: { Accept: "application/pdf" },
  });
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  const fallback = `BAST_${reportType}_${period.year}-${String(period.month).padStart(2, "0")}.pdf`;
  return {
    blob: await response.blob(),
    filename: filenameMatch?.[1] || fallback,
  };
}

export function getFollowUpDraft(
  csrfToken: string,
  nrp: string,
  period: Pick<PeriodView, "year" | "month">,
): Promise<FollowUpDraft> {
  return apiFetch<FollowUpDraft>(`${BASE}/talents/${encodeURIComponent(nrp)}/follow-up-draft`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ year: period.year, month: period.month }),
  });
}

export function sendFollowUp(
  csrfToken: string,
  nrp: string,
  period: Pick<PeriodView, "year" | "month">,
  message: string,
  source: FollowUpSource,
  idempotencyKey: string,
): Promise<FollowUpSendResponse> {
  return apiFetch<FollowUpSendResponse>(`${BASE}/talents/${encodeURIComponent(nrp)}/follow-ups`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      year: period.year,
      month: period.month,
      message,
      source,
      idempotency_key: idempotencyKey,
    }),
  });
}

export function getAttendanceGaps(year?: number, month?: number): Promise<AttendanceGapsResponse> {
  const query = year !== undefined && month !== undefined ? `?year=${year}&month=${month}` : "";
  return apiFetch<AttendanceGapsResponse>(`${BASE}/attendance-gaps${query}`);
}

export interface AttendanceGapSubmitInput {
  action: "worked" | "sakit" | "izin" | "cuti" | "libur";
  checkIn?: string;
  checkOut?: string;
  file: File;
}

export async function submitAttendanceGap(
  csrfToken: string,
  employeeId: string,
  attendanceKey: string,
  period: Pick<PeriodView, "year" | "month">,
  input: AttendanceGapSubmitInput,
): Promise<AttendanceGapMutationResponse> {
  const body = new FormData();
  // employee_id and attendance_key both contain literal "/" (e.g.
  // "MTG-TF/2024110292"), which breaks path-segment routing -- they travel
  // as form fields instead of URL path params.
  body.set("employee_id", employeeId);
  body.set("attendance_key", attendanceKey);
  body.set("action", input.action);
  if (input.checkIn) body.set("check_in", input.checkIn);
  if (input.checkOut) body.set("check_out", input.checkOut);
  body.set("file", input.file);
  const query = new URLSearchParams({ year: String(period.year), month: String(period.month) });
  // FormData bodies must set their own multipart Content-Type (with boundary);
  // apiFetch always forces application/json, so this goes through fetch directly.
  const response = await fetch(
    `${BASE}/attendance-gaps?${query.toString()}`,
    {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfToken },
      body,
    },
  );
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) message = payload.detail;
    } catch {
      // Preserve the status-based message when the response is not JSON.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as AttendanceGapMutationResponse;
}
