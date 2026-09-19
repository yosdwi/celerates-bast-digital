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

function cycleQuery(year?: number, month?: number): string {
  if (year === undefined || month === undefined) return "";
  return `?year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}`;
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
