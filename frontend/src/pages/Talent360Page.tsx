import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { askTalent } from "../api/talentops";
import type { AiInvestigation, CommandCenterResponse, TalentDetailResponse, TalentOpsSession } from "../api/types";
import FollowUpComposer from "../components/FollowUpComposer";
import { ChevronIcon, CloseIcon, SparkleIcon } from "../components/Icons";
import InvestigationCard from "../components/InvestigationCard";
import { StatusBadge, statusLabel } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { domainLabel } from "../domain/insights";

interface Props {
  session: TalentOpsSession;
  commandCenter: CommandCenterResponse;
  talent: TalentDetailResponse;
  onNavigate: (path: string) => void;
  onBack: () => void;
}

function dayNumber(value: string): number {
  return Number(value.slice(-2));
}

function dayLabel(value: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(new Date(`${value}T00:00:00`));
}

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

export default function Talent360Page({ session, commandCenter, talent, onNavigate, onBack }: Props) {
  const [search, setSearch] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState(`Why is ${talent.name} blocked and what should PMO verify first?`);
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiInvestigation, setAiInvestigation] = useState<AiInvestigation | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiUnavailable, setAiUnavailable] = useState(false);

  const issueCount = talent.blockers.reduce((total, blocker) => total + blocker.issues.length, 0);
  const closedTasks = talent.tasks.filter((task) => task.is_closed).length;
  const evidenceReady = talent.tasks.filter((task) => task.is_closed && task.evidence_ready === true).length;
  const timesheetIssues = talent.timesheet_days.filter((day) => day.state !== "complete");
  const attendanceIssues = talent.attendance_days.filter((day) => !day.is_off && day.state !== "complete");
  const primarySignal = talent.signals?.[0] ?? null;
  const firstWeekdayOffset = useMemo(() => {
    const first = talent.attendance_days[0];
    if (!first) return 0;
    const day = new Date(`${first.work_date}T00:00:00`).getDay();
    return day === 0 ? 6 : day - 1;
  }, [talent.attendance_days]);

  async function submitAi(event?: FormEvent) {
    event?.preventDefault();
    const question = aiQuestion.trim();
    if (!question || aiLoading) return;
    setAiLoading(true);
    setAiUnavailable(false);
    try {
      const response = await askTalent(session.csrf_token, talent.nrp, question, talent.period);
      setAiAnswer(response.answer);
      setAiInvestigation(response.investigation);
      setAiUnavailable(response.status === "unavailable");
    } catch {
      setAiAnswer(null);
      setAiInvestigation(null);
      setAiUnavailable(true);
    } finally {
      setAiLoading(false);
    }
  }

  function openInvestigation(question?: string) {
    if (question) setAiQuestion(question);
    setAiAnswer(null);
    setAiInvestigation(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  return (
    <WorkspaceFrame
      session={session}
      active="talents"
      attentionCount={commandCenter.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => openInvestigation()}
    >
      <div className="content slice2-content">
        <button className="talent-breadcrumb" type="button" onClick={onBack}>Talents <ChevronIcon /> <span>{talent.name}</span></button>

        <section className="talent-profile-head">
          <div className="talent-profile-identity">
            <div className="talent-profile-avatar">{initials(talent.name)}</div>
            <div><h1>{talent.name}</h1><p>{talent.role} · {talent.nrp} · {talent.period.label}</p></div>
          </div>
          <div className="talent-profile-actions">
            <button className="secondary-button" type="button" disabled title="Edit records in the existing NocoDB Data Workspace">Open data</button>
            <button className="primary-button" type="button" onClick={() => setFollowUpOpen(true)}>Follow up</button>
          </div>
        </section>

        <div className="talent-status-strip">
          <div><span>Overall</span><StatusBadge state={talent.overall_state} /></div>
          <div><span>Attendance</span><strong className={`text-${talent.checks.attendance.state}`}>{talent.checks.attendance.issue_count ? `${talent.checks.attendance.issue_count} issues` : statusLabel(talent.checks.attendance.state)}</strong></div>
          <div><span>Timesheet</span><strong className={`text-${talent.checks.timesheet.state}`}>{talent.checks.timesheet.issue_count ? `${talent.checks.timesheet.issue_count} issues` : statusLabel(talent.checks.timesheet.state)}</strong></div>
          <div><span>Tasks</span><strong>{closedTasks} / {talent.tasks.length} Closed</strong></div>
          <div><span>Evidence</span><strong>{talent.availability.evidence ? `${evidenceReady} / ${closedTasks} Closed tasks` : "Source unavailable"}</strong></div>
        </div>

        <div className="ai-insight-strip talent-ai-strip">
          <span className="ai-insight-icon"><SparkleIcon /></span>
          <div><strong>{primarySignal?.title ?? (issueCount === 0 ? "No blockers from current readiness rules." : `${issueCount} current readiness issues.`)}</strong>{primarySignal ? ` · ${primarySignal.summary}` : talent.blockers[0] ? ` · ${domainLabel(talent.blockers[0].domain)} needs review.` : ""}</div>
          <button type="button" onClick={() => openInvestigation()}>Investigate</button>
        </div>

        <div className="talent-tabs" role="tablist" aria-label="Talent detail sections">
          <button className="active" type="button">Overview</button>
          <button type="button" onClick={() => document.getElementById("attendance-section")?.scrollIntoView({ behavior: "smooth" })}>Attendance</button>
          <button type="button" onClick={() => document.getElementById("timesheet-section")?.scrollIntoView({ behavior: "smooth" })}>Timesheet</button>
          <button type="button" onClick={() => document.getElementById("tasks-section")?.scrollIntoView({ behavior: "smooth" })}>Tasks &amp; Evidence</button>
        </div>

        <div className="talent-detail-grid">
          <div className="talent-detail-main">
            <section className="panel talent-calendar-panel" id="attendance-section">
              <div className="panel-title-row"><div><h2>Attendance</h2><span>{talent.availability.attendance ? `${attendanceIssues.length} working days need review` : "Attendance source unavailable"}</span></div></div>
              <div className="calendar-weekdays">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day}>{day}</span>)}</div>
              <div className="attendance-calendar">
                {Array.from({ length: firstWeekdayOffset }, (_, index) => <div className="calendar-day blank" key={`blank-${index}`} />)}
                {talent.attendance_days.map((day) => {
                  const className = day.is_off ? "off" : day.state;
                  const detail = day.is_off
                    ? "OFF"
                    : day.state === "complete"
                      ? (day.has_evidence && !(day.has_clock_in && day.has_clock_out) ? "Evidence" : "Valid")
                      : day.state === "needs_review" ? "Source" : "Review";
                  return <div className={`calendar-day ${className}`} key={day.work_date} title={`${day.work_date}: ${detail}`}><strong>{dayNumber(day.work_date)}</strong><span>{detail}</span></div>;
                })}
              </div>
              <div className="calendar-legend"><span><i className="complete" />Valid</span><span><i className="incomplete" />Review</span><span><i className="off" />OFF</span><span><i className="needs_review" />Source review</span></div>
            </section>

            <section className="panel talent-task-panel" id="tasks-section">
              <div className="panel-title-row"><div><h2>Tasks &amp; Evidence</h2><span>{talent.tasks.length} tasks in selected period</span></div></div>
              {talent.tasks.length === 0 ? <div className="empty-state">No tasks are available for this period. Task readiness therefore requires review.</div> : null}
              <div className="desktop-table-wrap"><table className="data-table"><thead><tr><th>Date</th><th>Task</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{talent.tasks.map((task, index) => (
                <tr key={`${task.work_date}-${task.title}-${index}`}><td>{dayLabel(task.work_date)}</td><td><div className="talent-name">{task.title}</div></td><td>{task.status}</td><td>{task.evidence_ready === null ? "Source unavailable" : task.is_closed ? (task.evidence_ready ? `${task.evidence_count} attached` : "Missing") : "Not required yet"}</td></tr>
              ))}</tbody></table></div>
              <div className="mobile-operational-list slice2-mobile-list">{talent.tasks.map((task, index) => (
                <div className="task-mobile-card" key={`${task.work_date}-${task.title}-${index}`}><div><strong>{task.title}</strong><span>{dayLabel(task.work_date)} · {task.status}</span></div><span className={task.evidence_ready === false && task.is_closed ? "task-evidence-missing" : ""}>{task.evidence_ready === null ? "Evidence source unavailable" : task.is_closed ? (task.evidence_ready ? `${task.evidence_count} evidence` : "Evidence missing") : "Evidence pending close"}</span></div>
              ))}</div>
            </section>
          </div>

          <aside className="talent-detail-rail">
            <section className="panel rail-panel">
              <div className="panel-title-row"><div><h2>Readiness breakdown</h2><span>Deterministic completion rules</span></div></div>
              <div className="readiness-breakdown">{([['Attendance', talent.checks.attendance], ['Timesheet', talent.checks.timesheet], ['Task', talent.checks.task], ['Evidence', talent.checks.evidence]] as const).map(([label, check]) => <div key={label}><span>{label}</span><StatusBadge state={check.state} compact /></div>)}</div>
            </section>

            <section className="panel rail-panel">
              <div className="panel-title-row"><div><h2>Open issues</h2><span>{issueCount} rule findings</span></div></div>
              {talent.blockers.length === 0 ? <div className="empty-state">No readiness blockers in this period.</div> : <div className="blocker-list">{talent.blockers.map((blocker) => <div className="blocker-group" key={blocker.domain}><div><strong>{domainLabel(blocker.domain)}</strong><StatusBadge state={blocker.state} compact /></div>{blocker.issues.map((issue) => <p key={issue}>{issue}</p>)}</div>)}</div>}
            </section>

            <section className="panel rail-panel" id="timesheet-section">
              <div className="panel-title-row"><div><h2>Timesheet impact</h2><span>{timesheetIssues.length} dates need review</span></div></div>
              {timesheetIssues.length === 0 ? <div className="empty-state">No timesheet issues in this period.</div> : <div className="timesheet-issue-list">{timesheetIssues.map((day) => <div key={day.work_date}><strong>{dayLabel(day.work_date)}</strong><span>{day.blocked_by_attendance ? "Blocked by attendance validation" : day.is_off ? (day.has_record ? "OFF remarks missing" : "OFF timesheet missing") : "Timesheet missing"}</span></div>)}</div>}
            </section>
          </aside>
        </div>
      </div>

      {aiOpen ? (
        <div className="slice2-ai-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAiOpen(false); }}>
          <section className="slice2-ai-panel" role="dialog" aria-modal="true" aria-label={`Investigate ${talent.name}`}>
            <div className="slice2-ai-head"><div><SparkleIcon /><strong>Investigate · {talent.name}</strong></div><button type="button" className="icon-button" aria-label="Close investigation" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
            <p>Investigation is grounded in deterministic signals plus this talent's date-level Attendance, Timesheet, Task, and Evidence facts.</p>
            <div className="filter-chips" role="group" aria-label="Investigation prompts">
              <button type="button" onClick={() => setAiQuestion(`Why is ${talent.name} blocked and what should PMO verify first?`)}>Why blocked?</button>
              <button type="button" onClick={() => setAiQuestion("Which dates should PMO verify first, and are Attendance and Timesheet related?")}>Related dates</button>
              <button type="button" onClick={() => setAiQuestion("Which Closed tasks still have missing Evidence?")}>Missing evidence</button>
            </div>
            <form onSubmit={(event) => void submitAi(event)}><textarea value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} rows={4} /><button className="primary-button" type="submit" disabled={aiLoading}>{aiLoading ? "Investigating…" : "Investigate"}</button></form>
            {aiInvestigation ? <InvestigationCard investigation={aiInvestigation} /> : aiAnswer ? <div className="slice2-ai-answer">{aiAnswer}</div> : null}
            {aiUnavailable ? <div className="slice2-ai-answer muted">AI investigation is unavailable. Deterministic readiness and operational signals remain available above.</div> : null}
          </section>
        </div>
      ) : null}

      {followUpOpen ? (
        <FollowUpComposer
          session={session}
          nrp={talent.nrp}
          name={talent.name}
          period={talent.period}
          onClose={() => setFollowUpOpen(false)}
        />
      ) : null}
    </WorkspaceFrame>
  );
}
