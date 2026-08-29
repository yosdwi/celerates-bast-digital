import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter } from "../api/talentops";
import type { AttentionItem, CheckState, CommandCenterResponse, EmployeeRole, TalentOpsSession } from "../api/types";
import ApprovalQueue from "../components/ApprovalQueue";
import FollowUpComposer from "../components/FollowUpComposer";
import { ChevronIcon, CloseIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { domainLabel, primaryBlocker, totalIssues } from "../domain/insights";

type StateFilter = "all" | Exclude<CheckState, "complete">;
type TeamFilter = "all" | EmployeeRole;

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

function issuePreview(item: AttentionItem): string {
  const blocker = item.blockers[0];
  if (!blocker) return "Needs review";
  return blocker.issues[0] ?? `${domainLabel(blocker.domain)} needs review`;
}

function actionLabel(state: CheckState): string {
  if (state === "incomplete") return "Blocked";
  if (state === "needs_review") return "Review";
  return "Ready";
}

export default function ActionCenterPage({ session, data, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [selected, setSelected] = useState<AttentionItem | null>(null);
  const [followUpTarget, setFollowUpTarget] = useState<AttentionItem | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Summarize the current PMO action queue and the most common blockers.");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const queue = useMemo(
    () => data.attention.filter((item) => {
      const matchesState = stateFilter === "all" || item.overall_state === stateFilter;
      const matchesTeam = teamFilter === "all" || item.role === teamFilter;
      const matchesSearch = !normalizedSearch || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
      return matchesState && matchesTeam && matchesSearch;
    }),
    [data.attention, normalizedSearch, stateFilter, teamFilter],
  );

  const blockedCount = data.attention.filter((item) => item.overall_state === "incomplete").length;
  const reviewCount = data.attention.filter((item) => item.overall_state === "needs_review").length;
  const affectedDomains = new Set(data.attention.flatMap((item) => item.blockers.map((blocker) => blocker.domain))).size;

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

  function openFollowUp(item: AttentionItem) {
    setSelected(null);
    setFollowUpTarget(item);
  }

  return (
    <WorkspaceFrame
      session={session}
      active="actions"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => setAiOpen(true)}
    >
      <div className="content action-center-page">
        <div className="page-heading">
          <div>
            <h1>Action Center</h1>
            <p>{data.period.label} · deterministic readiness + shared PMO workflow queue</p>
          </div>
        </div>

        <div className="summary-strip action-summary" aria-label="Action Center summary">
          <div className="summary-item"><div className="summary-label">Open actions</div><div className="summary-value">{data.attention.length}</div><div className="summary-meta">Talents needing attention</div></div>
          <div className="summary-item"><div className="summary-label">Blocked</div><div className="summary-value">{blockedCount}</div><div className="summary-meta">Incomplete readiness</div></div>
          <div className="summary-item"><div className="summary-label">Needs review</div><div className="summary-value">{reviewCount}</div><div className="summary-meta">Manual review required</div></div>
          <div className="summary-item"><div className="summary-label">Domains affected</div><div className="summary-value">{affectedDomains}</div><div className="summary-meta">Attendance, timesheet, task, evidence</div></div>
        </div>

        <div className="ai-insight-strip action-ai-strip">
          <span className="ai-insight-icon"><SparkleIcon /></span>
          <div><strong>Actions are explicit.</strong> AI may explain or draft, but approval and WhatsApp sending remain explicit deterministic actions.</div>
          <button type="button" onClick={() => setAiOpen(true)}>Ask AI</button>
        </div>

        <ApprovalQueue session={session} />

        <section className="panel action-queue-panel">
          <div className="panel-title-row">
            <div><h2>Readiness action queue</h2><span>{data.attention.length} talents from current readiness rules</span></div>
          </div>
          <div className="toolbar action-toolbar">
            <div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search action queue" /></div>
            <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as StateFilter)} aria-label="Filter actions by state">
              <option value="all">All states</option>
              <option value="incomplete">Blocked</option>
              <option value="needs_review">Needs review</option>
            </select>
            <select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value as TeamFilter)} aria-label="Filter actions by team">
              <option value="all">All teams</option>
              <option value="Developer">Developer</option>
              <option value="IoT Operations">IoT Operations</option>
            </select>
          </div>

          {queue.length === 0 ? <div className="empty-state">No action items match this view.</div> : null}

          <div className="desktop-table-wrap">
            <table className="data-table action-table">
              <thead><tr><th>State</th><th>Talent</th><th>Primary blocker</th><th>Issues</th><th>Next</th><th aria-label="Open" /></tr></thead>
              <tbody>
                {queue.map((item) => (
                  <tr key={item.employee_id} onClick={() => setSelected(item)}>
                    <td><StatusBadge state={item.overall_state} compact /></td>
                    <td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td>
                    <td><div>{primaryBlocker(item)}</div><div className="cell-muted issue-preview">{issuePreview(item)}</div></td>
                    <td>{totalIssues(item)}</td>
                    <td><span className="action-next">{item.overall_state === "incomplete" ? "Resolve blocker" : "Review facts"}</span></td>
                    <td><button className="row-open" type="button" aria-label={`Open action for ${item.name}`}><ChevronIcon /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mobile-operational-list action-mobile-list">
            {queue.map((item) => (
              <button className="mobile-attention-row action-mobile-row" type="button" key={item.employee_id} onClick={() => setSelected(item)}>
                <div className="mobile-attention-top"><StatusBadge state={item.overall_state} compact /><span>{totalIssues(item)} issues</span></div>
                <div className="mobile-attention-name">{item.name}</div>
                <div className="mobile-attention-issue">{primaryBlocker(item)} · {issuePreview(item)}</div>
                <div className="mobile-attention-role">{item.nrp} · {item.role}</div>
                <ChevronIcon className="mobile-chevron" />
              </button>
            ))}
          </div>
        </section>

        <div className="action-rule-note">
          <strong>Queue semantics:</strong> readiness and approval are separate concerns. Approval changes typed workflow state; follow-up audit records communication only and never becomes a second task lifecycle.
        </div>
      </div>

      <div className={`drawer-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`detail-drawer ${selected ? "open" : ""}`} aria-hidden={!selected}>
        {selected ? <>
          <div className="drawer-header"><div><span>{selected.role}</span><h2>{selected.name}</h2><p>{selected.nrp}</p></div><button className="icon-button" type="button" aria-label="Close action details" onClick={() => setSelected(null)}><CloseIcon /></button></div>
          <div className="drawer-body">
            <div className="drawer-overall"><span>Action state</span><StatusBadge state={selected.overall_state} /></div>
            <div className="action-drawer-meta"><span>Interpretation</span><strong>{actionLabel(selected.overall_state)}</strong><span>{totalIssues(selected)} readiness issues</span></div>
            <h3>Blockers</h3>
            {selected.blockers.map((blocker) => <div className="blocker-card" key={blocker.domain}><div className="blocker-head"><strong>{domainLabel(blocker.domain)}</strong><StatusBadge state={blocker.state} compact /></div>{blocker.issues.length > 0 ? <ul>{blocker.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>No detailed issue text was returned.</p>}</div>)}
          </div>
          <div className="drawer-actions action-drawer-actions">
            <button className="secondary-button" type="button" onClick={() => openFollowUp(selected)}>WhatsApp follow-up</button>
            <button className="primary-button" type="button" onClick={() => { setSelected(null); onOpenTalent(selected.nrp); }}>Open Talent 360</button>
          </div>
        </> : null}
      </aside>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>Grounded in current Command Center facts</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}>
          <label htmlFor="action-ai-question">Question</label>
          <textarea id="action-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} />
          <button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}>{aiLoading ? "Thinking…" : "Ask"}</button>
          <div className="ai-safety-note">AI explains current facts. WhatsApp sending and approval are separate explicit actions.</div>
          {aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now. The deterministic action queue remains valid.</div> : null}
          {aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}
        </form>
      </section>

      {followUpTarget ? (
        <FollowUpComposer
          session={session}
          nrp={followUpTarget.nrp}
          name={followUpTarget.name}
          period={data.period}
          onClose={() => setFollowUpTarget(null)}
        />
      ) : null}
    </WorkspaceFrame>
  );
}
