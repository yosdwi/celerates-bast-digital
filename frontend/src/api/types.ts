export type CheckState = "complete" | "incomplete" | "needs_review";
export type EmployeeRole = "Developer" | "IoT Operations";

export interface SessionUser {
  name: string;
  role: string;
}

export interface TalentOpsSession {
  user: SessionUser;
  csrf_token: string;
  timezone: string;
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

export interface SourceFreshness {
  source_key: string;
  label: string;
  last_success_at: string | null;
  age_seconds: number | null;
}

export interface CommandCenterResponse {
  period: PeriodView;
  summary: CommandCenterSummary;
  attention: AttentionItem[];
  readiness: TalentReadiness[];
  teams: TeamReadiness[];
  delivery: DeliverySummary;
  sources: SourceFreshness[];
}

export interface AiResponse {
  status: "ok" | "unavailable";
  answer: string | null;
}
