import { apiFetch } from "./client";
import type { AiResponse, CommandCenterResponse, TalentDetailResponse, TalentOpsSession } from "./types";

const BASE = "/api/talentops/v1";

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
  period: { year: number; month: number },
): Promise<AiResponse> {
  return apiFetch<AiResponse>(`${BASE}/ai/command-center`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ year: period.year, month: period.month, question }),
  });
}
