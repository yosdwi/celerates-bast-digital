import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter } from "../api/talentops";
import type { AttentionItem, CommandCenterResponse, EmployeeRole, TalentOpsSession } from "../api/types";
import { ChevronIcon, CloseIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { domainLabel, totalIssues } from "../domain/insights";

type TeamFilter = "all" | EmployeeRole;

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

function taskBlocker(item: AttentionItem) {
  return item.blockers.find((blocker) => blocker.domain === "task");
}

export default function DeliveryPage({ session, data, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [selected, setSelected] = useState<AttentionItem | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Summarize current task delivery status and which PMO follow-ups are supported by the data.");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const taskAttention = useMemo(
    () => data.attention.filter((item) => {
      if (!taskBlocker(item)) return false;
      if (teamFilter !== "all" && item.role !== teamFilter) return false;
      return !normalizedSearch || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
    }),
    [data.attention, normalizedSearch, teamFilter],
  );

  async function submitAi(event?: FormEvent) {
    event?.preventDefault();
    const question = aiQuestion.trim();
    if (!question || aiLoading) return;
    setAiLoading(true);
    setAiUnavailable(false);
    try {
      const response = await askCommandCenter(session.csrf_token, question, data.period);
      setAiAnswer(response.answer);
      setAiUnavailable(response.status === "unavailable");
    } catch {
      setAiAnswer(null);
      setAiUnavailable(true);
    } finally {
      setAiLoading(false);
    }
  }

  function explain(item: AttentionItem) {
    setSelected(null);
    setAiQuestion(`Explain the task delivery blocker for ${item.name} (${item.nrp}) and what PMO should inspect next. Use only current Command Center facts.`);
    setAiAnswer(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  const closedPercent = data.delivery.total_tasks > 0
    ? Math.round((data.delivery.closed_tasks / data.delivery.total_tasks) * 100)
    : 0;

  return (
    <WorkspaceFrame
      session={session}
      active="delivery"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => setAiOpen(true)}
    >
      <div className="content delivery-page">
        <div className="page-heading"><div><h1>Delivery</h1><p>{data.period.label} · task movement from current typed records</p></div></div>

        <div className="summary-strip delivery-summary" aria-label="Delivery summary">
          <div className="summary-item"><div className="summary-label">Total tasks</div><div className="summary-value">{data.delivery.total_tasks}</div><div className="summary-meta">Selected period</div></div>
          <div className="summary-item"><div className="summary-label">Closed</div><div className="summary-value">{data.delivery.closed_tasks}</div><div className="summary-meta">{closedPercent}% of period tasks</div></div>
          <div className="summary-item"><div className="summary-label">Non-Closed</div><div className="summary-value">{data.delivery.non_closed_tasks}</div><div className="summary-meta">Current task status</div></div>
          <div className="summary-item"><div className="summary-label">Task blockers</div><div className="summary-value">{data.attention.filter((item) => taskBlocker(item)).length}</div><div className="summary-meta">Talents with task readiness issues</div></div>
        </div>

        <div className="ai-insight-strip delivery-ai-strip">
          <span className="ai-insight-icon"><SparkleIcon /></span>
          <div><strong>No closure trend is inferred.</strong> The current source does not preserve authoritative task close timestamps for weekly movement.</div>
          <button type="button" onClick={() => setAiOpen(true)}>Ask AI</button>
        </div>

        <div className="delivery-grid">
          <section className="panel delivery-status-panel">
            <div className="panel-title-row"><div><h2>Task status</h2><span>Distribution from selected-period task records</span></div></div>
            {data.delivery.status_counts.length === 0 ? <div className="empty-state">No tasks in this period.</div> : <div className="delivery-status-list">{data.delivery.status_counts.map((status) => {
              const width = data.delivery.total_tasks > 0 ? Math.max(3, (status.count / data.delivery.total_tasks) * 100) : 0;
              return <div className="delivery-status-row" key={status.status}><div><strong>{status.status}</strong><span>{status.count} tasks</span></div><div className="delivery-status-track"><span style={{ width: `${width}%` }} /></div><strong>{data.delivery.total_tasks > 0 ? Math.round((status.count / data.delivery.total_tasks) * 100) : 0}%</strong></div>;
            })}</div>}
          </section>

          <section className="panel delivery-team-panel">
            <div className="panel-title-row"><div><h2>Task readiness by team</h2><span>Same completion rules used by BAST readiness</span></div></div>
            <div className="delivery-team-list">{data.teams.map((team) => <div className="delivery-team-row" key={team.role}><div><strong>{team.role}</strong><span>{team.checks.task_ready} / {team.total} task-ready talents</span></div><div className="team-progress"><span style={{ width: team.total ? `${(team.checks.task_ready / team.total) * 100}%` : "0%" }} /></div></div>)}</div>
          </section>
        </div>

        <section className="panel delivery-blockers-panel">
          <div className="panel-title-row"><div><h2>Task blocker queue</h2><span>{data.attention.filter((item) => taskBlocker(item)).length} talents require task review</span></div></div>
          <div className="toolbar delivery-toolbar">
            <div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search task blockers" /></div>
            <select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value as TeamFilter)} aria-label="Filter task blockers by team"><option value="all">All teams</option><option value="Developer">Developer</option><option value="IoT Operations">IoT Operations</option></select>
          </div>

          {taskAttention.length === 0 ? <div className="empty-state">No task blockers match this view.</div> : null}
          <div className="desktop-table-wrap"><table className="data-table delivery-blocker-table"><thead><tr><th>Talent</th><th>Task state</th><th>Issue</th><th>Total issues</th><th aria-label="Open" /></tr></thead><tbody>{taskAttention.map((item) => {
            const blocker = taskBlocker(item)!;
            return <tr key={item.employee_id} onClick={() => setSelected(item)}><td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td><td><StatusBadge state={blocker.state} compact /></td><td><span className="delivery-issue">{blocker.issues[0] ?? `${domainLabel(blocker.domain)} needs review`}</span></td><td>{totalIssues(item)}</td><td><button className="row-open" type="button" aria-label={`Open task blocker for ${item.name}`}><ChevronIcon /></button></td></tr>;
          })}</tbody></table></div>

          <div className="mobile-operational-list delivery-mobile-list">{taskAttention.map((item) => {
            const blocker = taskBlocker(item)!;
            return <button className="mobile-attention-row delivery-mobile-row" type="button" key={item.employee_id} onClick={() => setSelected(item)}><div className="mobile-attention-top"><StatusBadge state={blocker.state} compact /><span>{totalIssues(item)} total issues</span></div><div className="mobile-attention-name">{item.name}</div><div className="mobile-attention-issue">{blocker.issues[0] ?? "Task readiness needs review"}</div><div className="mobile-attention-role">{item.nrp} · {item.role}</div><ChevronIcon className="mobile-chevron" /></button>;
          })}</div>
        </section>

        <div className="delivery-boundary-note"><strong>Analytics boundary:</strong> this page uses task statuses and readiness that exist today. Aging, weekly closure trend, utilization, capacity, and productivity scores are intentionally omitted until authoritative fields exist.</div>
      </div>

      <div className={`drawer-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`detail-drawer ${selected ? "open" : ""}`} aria-hidden={!selected}>
        {selected ? <><div className="drawer-header"><div><span>{selected.role}</span><h2>{selected.name}</h2><p>{selected.nrp}</p></div><button className="icon-button" type="button" aria-label="Close delivery details" onClick={() => setSelected(null)}><CloseIcon /></button></div><div className="drawer-body"><div className="drawer-overall"><span>Overall readiness</span><StatusBadge state={selected.overall_state} /></div><h3>Task blocker</h3>{taskBlocker(selected) ? <div className="blocker-card"><div className="blocker-head"><strong>Task</strong><StatusBadge state={taskBlocker(selected)!.state} compact /></div>{taskBlocker(selected)!.issues.length > 0 ? <ul>{taskBlocker(selected)!.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>No detailed task issue text was returned.</p>}</div> : <p>No task blocker is present.</p>}</div><div className="drawer-actions"><button className="secondary-button" type="button" onClick={() => explain(selected)}><SparkleIcon />Explain blocker</button><button className="primary-button" type="button" onClick={() => { setSelected(null); onOpenTalent(selected.nrp); }}>Open Talent 360</button></div></> : null}
      </aside>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>Grounded in current task and readiness facts</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="delivery-ai-question">Question</label><textarea id="delivery-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}>{aiLoading ? "Thinking…" : "Ask"}</button><div className="ai-safety-note">AI cannot infer utilization, capacity, velocity, or closure timestamps that are not present in the source data.</div>{aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now. Delivery facts above remain valid.</div> : null}{aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
