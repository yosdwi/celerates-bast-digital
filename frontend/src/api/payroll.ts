import { apiFetch } from "./client";

export type PayrollStatus =
  | "NEEDS_TALENT_ACTION"
  | "WAITING_SUBMITTED"
  | "COMPLETE";

export type PayrollScheduleState = "WORKING" | "OFF";
export type PayrollSourceState = "AVAILABLE" | "UNAVAILABLE";
export type PayrollReason =
  | "RAW_COMPLETE"
  | "SCHEDULED_OFF"
  | "SOURCE_UNAVAILABLE"
  | "GAP_UNCOVERED"
  | "CORRECTION_REJECTED"
  | "GAP_COVERED_BY_SUBMITTED_REQUEST"
  | "GAP_COVERED_BY_APPROVED_CORRECTION";

export type PayrollResolutionType =
  | "missing_clock_in"
  | "missing_clock_out"
  | "missing_both_worked"
  | "absence";

export type PayrollReviewabilityReason =
  | "talent_not_in_cycle"
  | "attendance_not_in_projection"
  | "source_unavailable"
  | "request_not_current"
  | "source_changed"
  | "evidence_not_found";

export type PayrollReviewDecision = "approve" | "reject";
export type PayrollReviewResultStatus = "succeeded" | "skipped" | "failed";
export type PayrollDeliveryState =
  | "RESERVED"
  | "SENDING"
  | "SENT"
  | "FAILED_RETRYABLE"
  | "FAILED_FINAL"
  | "UNKNOWN";
export type PayrollFollowUpReason =
  | "DELIVERY_UNKNOWN"
  | "DELIVERY_RETRYABLE_FAILED"
  | "DELIVERY_FINAL_FAILED"
  | "UNRESPONDED"
  | "NOT_REMINDED"
  | "WAITING_REVIEW"
  | "SOURCE_UNVERIFIED";

export interface PayrollCycle {
  cycle_id: string;
  label: string;
  year: number;
  month: number;
  start: string;
  end: string;
}

export interface PayrollCyclesResponse {
  current_cycle_id: string;
  cycles: PayrollCycle[];
}

export interface PayrollSummary {
  total_talents: number;
  complete: number;
  waiting_submitted: number;
  needs_talent_action: number;
  unverified: number;
}

export interface PayrollTalentRow {
  employee_id: string;
  nrp: string;
  name: string;
  role: string;
  status: PayrollStatus;
  evaluated_days: number;
  complete_days: number;
  waiting_days: number;
  actionable_days: number;
  unverified_days: number;
  talent_action_required: boolean;
}

export interface PayrollDay {
  attendance_id: number | null;
  attendance_key: string | null;
  work_date: string;
  schedule_state: PayrollScheduleState;
  source_state: PayrollSourceState;
  raw_check_in: string | null;
  raw_check_out: string | null;
  proposed_check_in: string | null;
  proposed_check_out: string | null;
  resolution_id: string | null;
  resolution_status: string | null;
  resolution_type: string | null;
  absence_type: string | null;
  rejection_reason: string | null;
  has_evidence: boolean;
  status: PayrollStatus;
  reason: PayrollReason;
  talent_action_required: boolean;
}

export interface PayrollOverviewResponse {
  cycle: PayrollCycle;
  evaluated_through: string | null;
  summary: PayrollSummary;
  talents: PayrollTalentRow[];
}

export interface PayrollTalentDetailResponse extends PayrollTalentRow {
  cycle: PayrollCycle;
  evaluated_through: string | null;
  days: PayrollDay[];
}

export interface PayrollReviewSummary {
  total: number;
  reviewable: number;
  stale: number;
  missing_clock_in: number;
  missing_clock_out: number;
  missing_both_worked: number;
  absence: number;
}

export interface PayrollReviewItem {
  request_id: string;
  attendance_id: number;
  employee_id: string;
  nrp: string;
  name: string;
  role: string;
  work_date: string;
  resolution_type: PayrollResolutionType;
  raw_check_in: string | null;
  raw_check_out: string | null;
  proposed_check_in: string | null;
  proposed_check_out: string | null;
  absence_type: string | null;
  evidence_id: string;
  evidence_content_type: string | null;
  evidence_byte_size: number | null;
  evidence_caption: string;
  evidence_uploaded_at: string | null;
  submitted_at: string;
  reviewable: boolean;
  reviewability_reason: PayrollReviewabilityReason | null;
}

export interface PayrollReviewQueueResponse {
  cycle: PayrollCycle;
  summary: PayrollReviewSummary;
  items: PayrollReviewItem[];
}

export interface PayrollReviewDecisionItem {
  request_id: string;
  status: PayrollReviewResultStatus;
  outcome: string;
}

export interface PayrollReviewDecisionResponse {
  requested: number;
  succeeded: number;
  skipped: number;
  failed: number;
  items: PayrollReviewDecisionItem[];
}

export interface PayrollClosingMilestone {
  label: string;
  days_before: number;
  work_date: string;
}

export interface PayrollClosingPreview {
  cycle: PayrollCycle;
  milestones: PayrollClosingMilestone[];
  estimated_actionable_talents: number;
  estimated_unverified_talents: number;
}

export interface PayrollClosingSettings {
  scope_key: string;
  enabled: boolean;
  paused: boolean;
  closing_day: number;
  reminder_hour: number;
  reminder_offsets: number[];
  target_roles: string[];
  next_day_ready_hour: number;
  desired_version: number;
  applied_version: number;
  updated_by: string | null;
  preview: PayrollClosingPreview;
}

export type PayrollClosingSettingsInput = Pick<
  PayrollClosingSettings,
  | "enabled"
  | "paused"
  | "closing_day"
  | "reminder_hour"
  | "reminder_offsets"
  | "target_roles"
  | "next_day_ready_hour"
>;

export interface PayrollDigestSummary {
  total_talents: number;
  complete: number;
  waiting_submitted: number;
  needs_talent_action: number;
  unverified: number;
  successful_reminder_deliveries: number;
  successfully_reminded_talents: number;
  unresponded_talents: number;
  actionable_not_reminded: number;
  delivery_retryable_failed: number;
  delivery_final_failed: number;
  delivery_unknown: number;
}

export interface PayrollFollowUpItem {
  employee_id: string;
  nrp: string;
  name: string;
  role: string;
  status: PayrollStatus;
  actionable_days: number;
  waiting_days: number;
  unverified_days: number;
  reason: PayrollFollowUpReason;
  latest_delivery_state: PayrollDeliveryState | null;
  latest_milestone: string | null;
  latest_sent_at: string | null;
  responded_at: string | null;
  error_code: string | null;
}

export interface PayrollDigestResponse {
  cycle: PayrollCycle;
  evaluated_through: string | null;
  summary: PayrollDigestSummary;
  items: PayrollFollowUpItem[];
}

export interface PayrollManualReminderPreview {
  employee_id: string;
  eligible: boolean;
  outcome: string;
  actionable_days: number;
  message: string | null;
}

export interface PayrollManualReminderResponse {
  employee_id: string;
  outcome: string;
  sent: boolean;
}

function cycleQuery(year?: number, month?: number): string {
  if (year === undefined || month === undefined) return "";
  return `?year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}`;
}

function followUpQuery(year?: number, month?: number): string {
  return cycleQuery(year, month);
}

export async function getPayrollCycles(): Promise<PayrollCyclesResponse> {
  return apiFetch<PayrollCyclesResponse>("/api/talentops/v1/payroll/cycles");
}

export async function getPayrollOverview(
  year?: number,
  month?: number,
): Promise<PayrollOverviewResponse> {
  return apiFetch<PayrollOverviewResponse>(
    `/api/talentops/v1/payroll/overview${cycleQuery(year, month)}`,
  );
}

export async function getPayrollTalentDetail(
  employeeId: string,
  year?: number,
  month?: number,
): Promise<PayrollTalentDetailResponse> {
  return apiFetch<PayrollTalentDetailResponse>(
    `/api/talentops/v1/payroll/talents/${encodeURIComponent(employeeId)}${cycleQuery(year, month)}`,
  );
}

export async function getPayrollReviewQueue(
  year?: number,
  month?: number,
): Promise<PayrollReviewQueueResponse> {
  return apiFetch<PayrollReviewQueueResponse>(
    `/api/talentops/v1/payroll/review-queue${cycleQuery(year, month)}`,
  );
}

export async function decidePayrollReviewQueue(
  csrfToken: string,
  year: number,
  month: number,
  requestIds: string[],
  decision: PayrollReviewDecision,
  rejectionReason?: string,
): Promise<PayrollReviewDecisionResponse> {
  return apiFetch<PayrollReviewDecisionResponse>(
    `/api/talentops/v1/payroll/review-queue/decide${cycleQuery(year, month)}`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({
        request_ids: requestIds,
        decision,
        rejection_reason: rejectionReason?.trim() || null,
      }),
    },
  );
}

export async function getPayrollClosingSettings(
  scopeKey = "default",
): Promise<PayrollClosingSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<PayrollClosingSettings>(
    `/api/talentops/v1/payroll/settings?${query.toString()}`,
  );
}

export async function savePayrollClosingSettings(
  csrfToken: string,
  input: PayrollClosingSettingsInput,
  scopeKey = "default",
): Promise<PayrollClosingSettings> {
  const query = new URLSearchParams({ scope_key: scopeKey });
  return apiFetch<PayrollClosingSettings>(
    `/api/talentops/v1/payroll/settings?${query.toString()}`,
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}

export async function getPayrollDigest(
  year?: number,
  month?: number,
): Promise<PayrollDigestResponse> {
  return apiFetch<PayrollDigestResponse>(
    `/api/talentops/v1/payroll/digest${followUpQuery(year, month)}`,
  );
}

export async function previewPayrollReminder(
  employeeId: string,
  year?: number,
  month?: number,
): Promise<PayrollManualReminderPreview> {
  return apiFetch<PayrollManualReminderPreview>(
    `/api/talentops/v1/payroll/follow-up/${encodeURIComponent(employeeId)}/preview${followUpQuery(year, month)}`,
  );
}

export async function sendManualPayrollReminder(
  csrfToken: string,
  employeeId: string,
  year: number,
  month: number,
  requestId: string,
): Promise<PayrollManualReminderResponse> {
  return apiFetch<PayrollManualReminderResponse>(
    `/api/talentops/v1/payroll/follow-up/${encodeURIComponent(employeeId)}/send${followUpQuery(year, month)}`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ request_id: requestId }),
    },
  );
}
