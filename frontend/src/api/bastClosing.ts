import { apiFetch } from "./client";

export interface BastSchedule {
  initial: string;
  followups: string[];
  closing: string;
  talent_reminder_dates: string[];
}

export interface BastClosingSettings {
  scope_key: string;
  enabled: boolean;
  initial_day: number;
  followup_offsets: number[];
  send_hour: number;
  timezone: string;
  talent_reminder_enabled: boolean;
  pmo_summary_enabled: boolean;
  pmo_group_jid: string | null;
  schedule: BastSchedule;
}

export interface EvidenceRule {
  task_category: string;
  evidence_required: boolean;
}

export interface BastBlastPreviewRow {
  nrp: string;
  name: string;
  actionable_count: number;
  status: "will_send" | "waiting_pmo" | "source_review";
}

export interface BastBlastPreview {
  total: number;
  will_send: number;
  waiting_pmo: number;
  complete: number;
  source_review: number;
  rows: BastBlastPreviewRow[];
}

export interface BastManualBlastResult {
  batch_id: string;
  eligible: number;
  sent: number;
  skipped: number;
  failed: number;
  scheduled_slot_consumed: boolean;
}

export async function getBastClosingSettings(year: number, month: number) {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiFetch<BastClosingSettings>(`/api/talentops/v1/bast-closing/settings?${query}`);
}

export async function saveBastClosingSettings(
  csrfToken: string,
  input: Omit<BastClosingSettings, "scope_key" | "timezone" | "schedule">,
) {
  return apiFetch<BastClosingSettings>("/api/talentops/v1/bast-closing/settings", {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  });
}

export async function getBastEvidenceRules() {
  return apiFetch<{ scope_key: string; rules: EvidenceRule[] }>(
    "/api/talentops/v1/bast-closing/evidence-rules",
  );
}

export async function saveBastEvidenceRules(csrfToken: string, rules: EvidenceRule[]) {
  return apiFetch<{ scope_key: string; rules: EvidenceRule[] }>(
    "/api/talentops/v1/bast-closing/evidence-rules",
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ rules }),
    },
  );
}

export async function previewBastBlast(year: number, month: number) {
  const query = new URLSearchParams({ year: String(year), month: String(month), target: "talent" });
  return apiFetch<BastBlastPreview>(`/api/talentops/v1/bast-closing/blast/preview?${query}`);
}

export async function sendBastBlast(csrfToken: string, year: number, month: number) {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiFetch<BastManualBlastResult>(`/api/talentops/v1/bast-closing/blast/send?${query}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}
