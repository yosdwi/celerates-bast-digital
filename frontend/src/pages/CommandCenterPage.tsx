import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter, askTalent } from "../api/talentops";
import type { AiInvestigation, AttentionItem, CommandCenterResponse, EmployeeRole, TalentOpsSession, TalentReadiness } from "../api/types";
import FollowUpComposer from "../components/FollowUpComposer";
import { ChevronIcon, CloseIcon, RefreshIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import InvestigationCard from "../components/InvestigationCard";
import { StatusBadge, statusLabel } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { deterministicInsight, domainLabel, primaryBlocker, readinessPercent, sourceAge, totalIssues } from "../domain/insights";

type TeamFilter = "all" | EmployeeRole;
type ReadinessFilter = "all" | EmployeeRole | "attention";

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  refreshing: boolean;
  onRefresh: () => void;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

function issuePreview(item: AttentionItem): string {
  const blocker = item.blockers[0];
  if (!blocker) return "Needs review";
  return blocker.issues[0] ?? `${domainLabel(blocker.domain)} needs review`;
}

function SummaryStrip({ data }: { data: CommandCenterResponse }) {
  const { summary } = data;
  return (
    <div className="summary-strip" aria-label="Command Center summary">
      <div className="summary-item"><div className="summary-label">BAST ready</div><div className="summary-value">{summary.bast_ready} / {summary.active_talents}</div><div className="summary-meta">{readinessPercent(summary.bast_ready, summary.active_talents)}</div></div>
      <div className="summary-item"><div className="summary-label">Need attention</div><div className="summary-value">{summary.need_attention}</div><div className="summary-meta">Current readiness rules</div></div>
      <div className="summary-item"><div className="summary-label">Open tasks</div><div className="summary-value">{summary.open_tasks}</div><div className="summary-meta">Non-Closed in period</div></div>
      <div className="summary-item"><div className="summary-label">Evidence ready</div><div className="summary-value">{summary.evidence_ready} / {summary.active_talents}</div><div className="summary-meta">{readinessPercent(summary.evidence_ready, summary.active_talents)}</div></div>
    </div>
  );
}

function StateCell({ state }: { state: TalentReadiness["overall_state"] }) {
  return <StatusBadge state={state} compact />;
}

export default function CommandCenterPage({ session, data, refreshing, onRefresh, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>("all");
  const [selected, setSelected] = useState<AttentionItem | null>(null);
  const [followUpTarget, setFollowUpTarget] = useState<AttentionItem | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiTarget, setAiTarget] = useState<AttentionItem | null>(null);
  const [aiQuestion, setAiQuestion] = useState("What should PMO pay attention to today?");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiInvestigation, setAiInvestigation] = useState<AiInvestigation | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const attention = useMemo(() => data.attention.filter((item) => {
    const teamOk = teamFilter === "all" || item.role === teamFilter;
    const searchOk = !normalizedSearch || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
    return teamOk && searchOk;
  }), [data.attention, normalizedSearch, teamFilter]);

  const readiness = useMemo(() => data.readiness.filter((item) => {
    const filterOk = readinessFilter === "all" || (readinessFilter === "attention" ? item.overall_state !== "complete" : item.role === readinessFilter);
    const searchOk = !normalizedSearch || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
    return filterOk && searchOk;
  }), [data.readiness, normalizedSearch, readinessFilter]);

  async function submitAi(event?: FormEvent) {
    event?.preventDefault();
    const question = aiQuestion.trim();
    if (!question || aiLoading) return;
    setAiLoading(true);
    setAiUnavailable(false);
    try {
      const response = aiTarget
        ? await askTalent(session.csrf_token, aiTarget.nrp, question, data.period)
        : await askCommandCenter(session.csrf_token, question, data.period);
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

  function openGlobalAi() {
    setAiTarget(null);
    setAiQuestion("What should PMO pay attention to today?");
    setAiAnswer(null);
    setAiInvestigation(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  function askAbout(item: AttentionItem) {
    setSelected(null);
    setAiTarget(item);
    setAiQuestion(`Why is ${item.name} blocked and what should PMO verify first?`);
    setAiAnswer(null);
    setAiInvestigation(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  function openFollowUp(item: AttentionItem) {
    setSelected(null);
    setFollowUpTarget(item);
  }

  const insight = deterministicInsight(data);

  return (
    <WorkspaceFrame session={session} active="command-center" attentionCount={data.summary.need_attention} search={search} onSearch={setSearch} onNavigate={onNavigate} onAskAi={openGlobalAi}>
      <div className="content">
        <div className="page-heading"><div><h1>Command Center</h1><p>{data.period.label}</p></div><button className="secondary-button refresh-button" type="button" disabled={refreshing} onClick={onRefresh}><RefreshIcon />{refreshing ? "Refreshing" : "Refresh"}</button></div>
        <SummaryStrip data={data} />
        <div className="ai-insight-strip"><span className="ai-insight-icon"><SparkleIcon /></span><div><strong>{insight.split(" · ")[0]}</strong>{insight.includes(" · ") ? ` · ${insight.split(" · ").slice(1).join(" · ")}` : ""}</div><button type="button" onClick={openGlobalAi}>Investigate</button></div>

        <div className="top-grid">
          <section className="panel attention-panel">
            <div className="panel-title-row"><div><h2>Need Attention</h2><span>{data.attention.length} talents from current readiness rules</span></div></div>
            <div className="toolbar"><div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search Need Attention" /></div><select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value as TeamFilter)} aria-label="Filter attention by team"><option value="all">All teams</option><option value="Developer">Developer</option><option value="IoT Operations">IoT Operations</option></select></div>
            {attention.length === 0 ? <div className="empty-state">No attention items match this view.</div> : null}
            <div className="desktop-table-wrap"><table className="data-table"><thead><tr><th>State</th><th>Talent</th><th>Primary blocker</th><th>Issues</th><th aria-label="Open" /></tr></thead><tbody>{attention.map((item) => <tr key={item.employee_id} onClick={() => setSelected(item)}><td><StatusBadge state={item.overall_state} compact /></td><td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td><td><div>{primaryBlocker(item)}</div><div className="cell-muted issue-preview">{issuePreview(item)}</div></td><td>{totalIssues(item)}</td><td><button className="row-open" type="button" aria-label={`Open ${item.name}`}><ChevronIcon /></button></td></tr>)}</tbody></table></div>
            <div className="mobile-operational-list">{attention.map((item) => <button className="mobile-attention-row" type="button" key={item.employee_id} onClick={() => setSelected(item)}><div className="mobile-attention-top"><StatusBadge state={item.overall_state} compact /><span>{totalIssues(item)} issues</span></div><div className="mobile-attention-name">{item.name}</div><div className="mobile-attention-issue">{primaryBlocker(item)} · {issuePreview(item)}</div><div className="mobile-attention-role">{item.nrp} · {item.role}</div><ChevronIcon className="mobile-chevron" /></button>)}</div>
          </section>

          <section className="panel sources-panel"><div className="panel-title-row"><div><h2>Sources</h2><span>Last successful server ingest</span></div></div><div className="source-list">{data.sources.map((source) => <div className="source-row" key={source.source_key}><span className={`source-dot ${source.last_success_at ? "observed" : "unknown"}`} /><div><strong>{source.label}</strong><span>{source.last_success_at ? new Date(source.last_success_at).toLocaleString() : "No successful ingest observed"}</span></div><div className="source-age">{sourceAge(source)}</div></div>)}</div><div className="source-note">Freshness is shown as observed age only. No SLA threshold is inferred.</div></section>
        </div>

        <section className="panel readiness-panel">
          <div className="panel-title-row"><div><h2>Talent Readiness</h2><span>{data.summary.active_talents} active talents</span></div></div>
          <div className="filter-chips" role="group" aria-label="Talent readiness filters">{([['all','All'],['Developer','Developer'],['IoT Operations','IoT Operations'],['attention','Attention only']] as const).map(([value,label]) => <button key={value} type="button" className={readinessFilter === value ? "active" : ""} onClick={() => setReadinessFilter(value)}>{label}</button>)}</div>
          {readiness.length === 0 ? <div className="empty-state">No talents match this filter.</div> : null}
          <div className="desktop-table-wrap"><table className="data-table readiness-table"><thead><tr><th>Talent</th><th>Attendance</th><th>Timesheet</th><th>Task</th><th>Evidence</th><th>Overall</th></tr></thead><tbody>{readiness.map((item) => <tr className="talent-link-row" key={item.employee_id} onClick={() => onOpenTalent(item.nrp)}><td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td><td><StateCell state={item.checks.attendance.state} /></td><td><StateCell state={item.checks.timesheet.state} /></td><td><StateCell state={item.checks.task.state} /></td><td><StateCell state={item.checks.evidence.state} /></td><td><StateCell state={item.overall_state} /></td></tr>)}</tbody></table></div>
          <div className="mobile-operational-list readiness-mobile-list">{readiness.map((item) => <button className="mobile-readiness-row talent-link-row" type="button" key={item.employee_id} onClick={() => onOpenTalent(item.nrp)}><div className="mobile-readiness-head"><div><strong>{item.name}</strong><span>{item.nrp} · {item.role}</span></div><StatusBadge state={item.overall_state} compact /></div><div className="mobile-readiness-grid">{([['Attendance',item.checks.attendance],['Timesheet',item.checks.timesheet],['Task',item.checks.task],['Evidence',item.checks.evidence]] as const).map(([label,check]) => <div key={label}><span>{label}</span><strong className={`text-${check.state}`}>{statusLabel(check.state)}</strong></div>)}</div></button>)}</div>
        </section>

        <div className="lower-grid">
          <section className="flat-section"><div className="flat-heading"><h2>Delivery</h2><span>Task status in selected period</span></div><div className="delivery-stats"><div><strong>{data.delivery.closed_tasks}</strong><span>Closed</span></div><div><strong>{data.delivery.non_closed_tasks}</strong><span>Non-Closed</span></div><div><strong>{data.delivery.total_tasks}</strong><span>Total</span></div></div>{data.delivery.status_counts.length > 0 ? <div className="status-counts">{data.delivery.status_counts.map((status) => <span key={status.status}>{status.status} <strong>{status.count}</strong></span>)}</div> : <div className="flat-empty">No tasks in this period.</div>}</section>
          <section className="flat-section"><div className="flat-heading"><h2>Team readiness</h2><span>Counts from the same completion rules</span></div><div className="team-list">{data.teams.map((team) => <div className="team-row" key={team.role}><div className="team-row-head"><strong>{team.role}</strong><span>{team.ready} / {team.total} ready</span></div><div className="team-progress"><span style={{ width: team.total ? `${(team.ready / team.total) * 100}%` : "0%" }} /></div><div className="team-checks"><span>Attendance {team.checks.attendance_ready}/{team.total}</span><span>Timesheet {team.checks.timesheet_ready}/{team.total}</span><span>Task {team.checks.task_ready}/{team.total}</span><span>Evidence {team.checks.evidence_ready}/{team.total}</span></div></div>)}</div></section>
        </div>
        <footer className="prototype-footer">Readiness is calculated from the current typed PostgreSQL data and shared completion rules.</footer>
      </div>

      <div className={`drawer-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`detail-drawer ${selected ? "open" : ""}`} aria-hidden={!selected}>{selected ? <><div className="drawer-header"><div><span>{selected.role}</span><h2>{selected.name}</h2><p>{selected.nrp}</p></div><button className="icon-button" type="button" aria-label="Close details" onClick={() => setSelected(null)}><CloseIcon /></button></div><div className="drawer-body"><div className="drawer-overall"><span>Overall</span><StatusBadge state={selected.overall_state} /></div><h3>Blockers</h3>{selected.blockers.map((blocker) => <div className="blocker-card" key={blocker.domain}><div className="blocker-head"><strong>{domainLabel(blocker.domain)}</strong><StatusBadge state={blocker.state} compact /></div>{blocker.issues.length ? <ul>{blocker.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>No detailed issue text was returned.</p>}</div>)}</div><div className="drawer-actions"><button className="secondary-button" type="button" onClick={() => askAbout(selected)}><SparkleIcon />Investigate blockers</button><button className="secondary-button" type="button" onClick={() => openFollowUp(selected)}>WhatsApp follow-up</button><button className="primary-button" type="button" onClick={() => { setSelected(null); onOpenTalent(selected.nrp); }}>Open talent</button></div></> : null}</aside>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}><div className="ai-panel-header"><div><span>{aiTarget ? `Grounded in ${aiTarget.name}'s current facts` : "Grounded in Command Center facts"}</span><h2>Investigate</h2></div><button className="icon-button" type="button" aria-label="Close investigation" onClick={() => setAiOpen(false)}><CloseIcon /></button></div><form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="ai-question">Question</label><textarea id="ai-question" rows={3} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}>{aiLoading ? "Investigating…" : "Investigate"}</button>{aiUnavailable ? <div className="ai-unavailable">AI investigation is unavailable right now. Deterministic readiness and operational signals remain valid.</div> : null}{aiInvestigation ? <InvestigationCard investigation={aiInvestigation} /> : aiAnswer ? <div className="ai-answer"><span>Finding</span><p>{aiAnswer}</p></div> : null}</form></section>

      {followUpTarget ? <FollowUpComposer session={session} nrp={followUpTarget.nrp} name={followUpTarget.name} period={data.period} onClose={() => setFollowUpTarget(null)} /> : null}
    </WorkspaceFrame>
  );
}
