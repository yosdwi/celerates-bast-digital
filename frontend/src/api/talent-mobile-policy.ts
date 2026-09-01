import { apiFetch } from "./client";

const BASE = "/api/talentops/v1";

export interface TalentMobileLinkPolicy {
  scope_key: string;
  ttl_days: number;
}

export function getTalentMobileLinkPolicy(scopeKey = "default"): Promise<TalentMobileLinkPolicy> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<TalentMobileLinkPolicy>(`${BASE}/talent-mobile-link-policy?${query.toString()}`);
}

export function saveTalentMobileLinkPolicy(
  csrfToken: string,
  ttlDays: number,
  scopeKey = "default",
): Promise<TalentMobileLinkPolicy> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<TalentMobileLinkPolicy>(`${BASE}/talent-mobile-link-policy?${query.toString()}`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ ttl_days: ttlDays }),
  });
}
