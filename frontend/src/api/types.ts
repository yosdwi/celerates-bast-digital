export type CheckState = "complete" | "incomplete" | "needs_review";
export type EmployeeRole = "Developer" | "IoT Operations";
export type FollowUpSource = "deterministic" | "ai" | "edited";
export type FollowUpStatus = "sent" | "not_bound" | "bridge_unavailable" | "failed" | "no_blockers";
export type OperationalSignalKind =
  | "attendance_blocks_timesheet"
  | "closed_task_missing_evidence"
  | "multi_domain_blocker"
  | "team_domain_gap";

export interface SessionUser {
  name: string;
  role: string;
}

export interface TalentOpsSession {
  user: SessionUser;
  csrf_token: string;
  timezone: string;
}

export interface WhatsAppStatus {
  connection: string;
  me: string;
  provider: string;
}

export interface PeriodView {
  year: number;
  month: number;
  start: string;
  end: string;
  label: string;
}

export interface CommandCenterSummary {
  active_talents: number;
  bast_ready: number;
  need_attention: number;
  open_tasks: number;
  evidence_ready: number;
}

export interface CheckSummary {
  state: CheckState;
  issue_count: number;
}

export interface ReadinessChecks {
  attendance: CheckSummary;
  timesheet: CheckSummary;
  task: CheckSummary;
  evidence: CheckSummary;
}

export interface Blocker {
  domain: "attendance" | "timesheet" | "task" | "evidence" | string;
  state: CheckState;
  issues: string[];
}

export interface AttentionItem {
  employee_id: string;
  nrp: string;
  name: string;
  role: EmployeeRole;
  overall_state: CheckState;
  blockers: Blocker[];
}

export interface TalentReadiness {
  employee_id: string;
  nrp: string;
  name: string;
  role: EmployeeRole;
  overall_state: CheckState;
  checks: ReadinessChecks;
}

export interface TeamCheckCounts {
  attendance_ready: number;
  timesheet_ready: number;
  task_ready: number;
  evidence_ready: number;
}

export interface TeamReadiness {
  role: EmployeeRole;
  total: number;
  ready: number;
  checks: TeamCheckCounts;
}

export interface TaskStatusCount {
  status: string;
  count: number;
}

export interface DeliverySummary {
  total_tasks: number;
  closed_tasks: number;
  non_closed_tasks: number;
  status_counts: TaskStatusCount[];
}

export interface TaskEvidenceItem {
  id: string;
  employee_id: string;
  nrp: string;
  full_name: string;
  role: EmployeeRole;
  task_id: number;
  work_date: string;
  task_title: string;
  task_source: string;
  caption: string;
  content_type: string;
  byte_size: number;
  uploaded_at: string;
  image_url: string;
}

export interface TaskEvidencePage {
  items: TaskEvidenceItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SourceFreshness {
  source_key: string;
  label: string;
  last_success_at: string | null;
  age_seconds: number | null;
}

export interface OperationalSignal {
  kind: OperationalSignalKind;
  title: string;
  summary: string;
  domains: string[];
  dates: string[];
  task_titles: string[];
  nrp: string | null;
  role: EmployeeRole | null;
}

export interface CommandCenterResponse {
  period: PeriodView;
  summary: CommandCenterSummary;
  attention: AttentionItem[];
  readiness: TalentReadiness[];
  teams: TeamReadiness[];
  delivery: DeliverySummary;
  sources: SourceFreshness[];
  signals?: OperationalSignal[];
}

export interface AttendanceDay {
  work_date: string;
  is_off: boolean;
  has_record: boolean;
  has_clock_in: boolean;
  has_clock_out: boolean;
  has_evidence: boolean;
  state: CheckState;
}

export interface TimesheetDay {
  work_date: string;
  is_off: boolean;
  has_record: boolean;
  has_remarks: boolean;
  blocked_by_attendance: boolean;
  state: CheckState;
}

export interface TalentTask {
  work_date: string;
  title: string;
  status: string;
  evidence_count: number;
  is_closed: boolean;
  evidence_ready: boolean | null;
}

export interface TalentDataAvailability {
  attendance: boolean;
  evidence: boolean;
}

export interface TalentDetailResponse {
  period: PeriodView;
  nrp: string;
  name: string;
  role: EmployeeRole;
  overall_state: CheckState;
  checks: ReadinessChecks;
  blockers: Blocker[];
  attendance_days: AttendanceDay[];
  timesheet_days: TimesheetDay[];
  tasks: TalentTask[];
  availability: TalentDataAvailability;
  signals?: OperationalSignal[];
}

export interface AttendanceResolution {
  id: string;
  attendance_id: number;
  employee_id: string;
  nrp: string;
  full_name: string;
  work_date: string;
  resolution_type: "missing_clock_in" | "missing_clock_out" | "missing_both_worked" | "absence";
  absence_type: "cuti" | "izin" | "sakit" | null;
  proposed_check_in: string | null;
  proposed_check_out: string | null;
  status: "pending" | "approved" | "rejected";
  evidence_id: string;
  submitted_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
}

export interface IdentityRebindRequest {
  id: string;
  employee_id: string;
  nrp: string;
  full_name: string;
  old_wa_jid: string;
  new_wa_jid: string;
  scope_key: string;
  status: "pending" | "approved" | "rejected";
  requested_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
}

export interface WorkflowOperator {
  email: string;
  display_name: string;
  role: "admin" | "pmo";
  scope_key: string;
  active: boolean;
  can_approve_attendance: boolean;
  can_approve_rebind: boolean;
  can_generate_bast: boolean;
  whatsapp_notify: boolean;
  whatsapp_jid: string | null;
}

export interface WorkflowOperatorInput {
  display_name: string;
  scope_key: string;
  active: boolean;
  can_approve_attendance: boolean;
  can_approve_rebind: boolean;
  can_generate_bast: boolean;
  whatsapp_notify: boolean;
}

export interface WhatsAppInvite {
  operator_email: string;
  token: string;
  expires_at: string;
}

export interface NotificationSettings {
  scope_key: string;
  attendance_immediate: boolean;
  rebind_immediate: boolean;
  reminder_hour: number;
  talent_reminder_days: number[];
  pmo_reminder_days: number[];
}

export interface TalentMobileSettings {
  scope_key: string;
  public_url: string | null;
}

export interface BastBlocker {
  employee_id: string;
  nrp: string;
  name: string;
  domain: string;
  state: string;
  issues: string[];
}

export interface BastReadiness {
  report_type: "developer" | "iotoperation";
  role: EmployeeRole;
  total_talents: number;
  ready_talents: number;
  ready: boolean;
  blockers: BastBlocker[];
}

export interface AiEvidence {
  id: string;
  kind: string;
  label: string;
  detail: string;
  domains: string[];
  work_date: string | null;
  task_title: string | null;
  nrp: string | null;
}

export interface AiInvestigation {
  title: string;
  finding: string;
  impact: string | null;
  suggested_action: string | null;
  evidence: AiEvidence[];
}

export interface AiResponse {
  status: "ok" | "unavailable";
  answer: string | null;
  investigation: AiInvestigation | null;
}

export interface FollowUpRecord {
  id: string;
  source: string;
  status: string;
  created_by: string;
  created_at: string;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  failed_at: string | null;
  delivery_error_code: string | null;
}

export interface FollowUpDraft {
  nrp: string;
  name: string;
  whatsapp_bound: boolean;
  message: string;
  source: FollowUpSource;
  last_follow_up: FollowUpRecord | null;
}

export interface FollowUpSendResponse {
  status: FollowUpStatus;
  delivery_id: string | null;
  provider_message_id: string | null;
  sent_at: string | null;
  error_code: string | null;
  duplicate: boolean;
}
