import { apiFetch } from "./client";
import type { EmployeeRole, PeriodView } from "./types";

const BASE = "/api/talentops/v1";

export type TalentMobileLinkStatus = "ready" | "not_configured";

export interface TalentMobileLinkItem {
  employee_id: string;
  nrp: string;
  name: string;
  role: EmployeeRole;
  whatsapp_bound: boolean;
  status: TalentMobileLinkStatus;
  url: string | null;
}

export interface TalentMobileLinksResponse {
  year: number;
  month: number;
  period_label: string;
  ttl_seconds: number;
  items: TalentMobileLinkItem[];
}

export function getTalentMobileLinks(
  period: Pick<PeriodView, "year" | "month">,
): Promise<TalentMobileLinksResponse> {
  const query = new URLSearchParams({
    year: String(period.year),
    month: String(period.month),
  });
  return apiFetch<TalentMobileLinksResponse>(`${BASE}/talent-mobile-links?${query.toString()}`);
}
