import { apiFetch, apiFetchResponse } from "./client";
import type {
  AiResponse,
  CommandCenterResponse,
  FollowUpDraft,
  FollowUpSendResponse,
  FollowUpSource,
  PeriodView,
  TalentDetailResponse,
  TalentOpsSession,
} from "./types";

const BASE = "/api/talentops/v1";

export type BastReportType = "developer" | "iotoperation";

export interface GeneratedBastFile {
  blob: Blob;
  filename: string;
}

export function getSession(): Promise<TalentOpsSession> {
  return apiFetch<TalentOpsSession>(`${BASE}/session`);
}

export function getCommandCenter(year?: number, month?: number): Promise<CommandCenterResponse> {
  const query = year !== undefined && month !== undefined ? `?year=${year}&month=${month}` : "";
  return apiFetch<CommandCenterResponse>(`${BASE}/command-center${query}`);
}

export function getTalentDetail(nrp: string, year: number, month: number): Promise<TalentDetailResponse> {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiFetch<TalentDetailResponse>(`${BASE}/talents/${encodeURIComponent(nrp)}?${query.toString()}`);
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
): Promise<GeneratedBastFile> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
    report_type: reportType,
  });
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
