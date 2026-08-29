import { apiFetch, apiFetchResponse } from "./client";
import type {
  AiResponse,
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
  TalentOpsSession,
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
  mode: BastGenerationMode;
  readiness: "ready" | "blocked";
  forced: boolean;
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

export async function generateBast(
  csrfToken: string,
  period: Pick<PeriodView, "year" | "month">,
  reportType: BastReportType,
  mode: BastGenerationMode = "final",
  force = false,
  forceReason = "",
): Promise<GeneratedBastFile> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    report_type: reportType,
    mode,
    force: String(force),
  });
  if (forceReason.trim()) query.set("force_reason", forceReason.trim());
  const response = await apiFetchResponse(`${BASE}/bast/generate?${query.toString()}`, {
    method: "POST",
    headers: {
      Accept: "application/pdf",
      "X-CSRF-Token": csrfToken,
    },
  });
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  const fallback = `BAST_${reportType}_${period.year}-${String(period.month).padStart(2, "0")}.pdf`;
  return {
    blob: await response.blob(),
    filename: filenameMatch?.[1] || fallback,
    mode: (response.headers.get("X-BAST-Mode") as BastGenerationMode | null) ?? mode,
    readiness: response.headers.get("X-BAST-Readiness") === "blocked" ? "blocked" : "ready",
    forced: response.headers.get("X-BAST-Forced") === "true",
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
