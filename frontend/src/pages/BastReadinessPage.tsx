import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter, generateBast } from "../api/talentops";
import type { BastReportType } from "../api/talentops";
import type { CheckState, CommandCenterResponse, EmployeeRole, TalentOpsSession, TalentReadiness } from "../api/types";
import { ChevronIcon, CloseIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { domainLabel, readinessPercent } from "../domain/insights";

type StateFilter = "all" | CheckState;
type TeamFilter = "all" | EmployeeRole;
type GenerationState = "idle" | "generating" | "success" | "error";

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
  onOpenTalent: (nrp: string) => void;
}

interface ReadinessRow extends TalentReadiness {
  blockerDomains: string[];
  issueCount: number;
}

function firstBlockerLabel(row: ReadinessRow): string {
  if (row.overall_state === "complete") return "No blockers";
  return row.blockerDomains.length ? row.blockerDomains.map(domainLabel).join(", ") : "Needs review";
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function BastReadinessPage({ session, data, onNavigate, onOpenTalent }: Props) {
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [selected, setSelected] = useState<ReadinessRow | null>(null);
  const [bastReportType, setBastReportType] = useState<BastReportType>("developer");
  const [generationState, setGenerationState] = useState<GenerationState>("idle");
  const [generationMessage, setGenerationMessage] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Summarize the current BAST readiness blockers and what PMO should close first.");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const rows = useMemo<ReadinessRow[]>(() => {
    const attentionByNrp = new Map(data.attention.map((item) => [item.nrp, item]));
    return data.readiness.map((item) => {
      const attention = attentionByNrp.get(item.nrp);
      const blockerDomains = attention?.blockers.map((blocker) => blocker.domain) ?? [];
      const issueCount = Object.values(item.checks).reduce((sum, check) => sum + check.issue_count, 0);
      return { ...item, blockerDomains, issueCount };
    });
  }, [data.attention, data.readiness]);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filtered = useMemo(
    () => rows.filter((item) => {
      const stateOk = stateFilter === "all" || item.overall_state === stateFilter;
      const teamOk = teamFilter === "all" || item.role === teamFilter;
      const searchOk = !normalizedSearch || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
      return stateOk && teamOk && searchOk;
    }),
    [normalizedSearch, rows, stateFilter, teamFilter],
  );

  const blockedCount = rows.filter((item) => item.overall_state === "incomplete").length;
  const reviewCount = rows.filter((item) => item.overall_state === "needs_review").length;
  const readyCount = rows.filter((item) => item.overall_state === "complete").length;

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

  async function submitBastGeneration() {
    if (generationState === "generating") return;
    setGenerationState("generating");
    setGenerationMessage("");
    try {
      const generated = await generateBast(session.csrf_token, data.period, bastReportType);
      triggerDownload(generated.blob, generated.filename);
      setGenerationState("success");
      setGenerationMessage(`${generated.filename} generated.`);
    } catch (error) {
      setGenerationState("error");
      setGenerationMessage(error instanceof Error ? error.message : "BAST generation failed.");
    }
  }

  function explainTalent(item: ReadinessRow) {
    setSelected(null);
    setAiQuestion(`Explain the BAST readiness blockers for ${item.name} (${item.nrp}) and the safest next PMO review step. Use only current readiness facts.`);
    setAiAnswer(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  return (
    <WorkspaceFrame
      session={session}
      active="bast"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => setAiOpen(true)}
    >
      <div className="content bast-readiness-page">
        <div className="page-heading bast-heading">
          <div><h1>BAST Readiness</h1><p>{data.period.label} · closing readiness from shared completion rules</p></div>
          <div className="bast-generation">
            <div className="bast-generation-controls">
              <select
                aria-label="BAST report type"
                value={bastReportType}
                disabled={generationState === "generating"}
                onChange={(event) => setBastReportType(event.target.value as BastReportType)}
              >
                <option value="developer">Developer</option>
                <option value="iotoperation">IoT Operations</option>
              </select>
              <button
                className="primary-button"
                type="button"
                disabled={generationState === "generating"}
                onClick={submitBastGeneration}
              >
                {generationState === "generating" ? "Generating…" : "Generate BAST"}
              </button>
            </div>
            {generationState === "success" ? <div className="bast-generation-status success" role="status">{generationMessage}</div> : null}
            {generationState === "error" ? <div className="bast-generation-status error" role="alert">{generationMessage}</div> : null}
          </div>
        </div>

        <div className="summary-strip bast-summary" aria-label="BAST readiness summary">
          <div className="summary-item"><div className="summary-label">Ready</div><div className="summary-value">{readyCount} / {rows.length}</div><div className="summary-meta">{readinessPercent(readyCount, rows.length)}</div></div>
          <div className="summary-item"><div className="summary-label">Blocked</div><div className="summary-value">{blockedCount}</div><div className="summary-meta">Incomplete readiness</div></div>
          <div className="summary-item"><div className="summary-label">Needs review</div><div className="summary-value">{reviewCount}</div><div className="summary-meta">Manual review required</div></div>
          <div className="summary-item"><div className="summary-label">Evidence ready</div><div className="summary-value">{data.summary.evidence_ready} / {data.summary.active_talents}</div><div className="summary-meta">Same deterministic rules</div></div>
        </div>

        <div className="ai-insight-strip bast-ai-strip">
          <span className="ai-insight-icon"><SparkleIcon /></span>
          <div><strong>Readiness is not generated by AI.</strong> AI may explain blockers; deterministic completion rules remain authoritative.</div>
          <button type="button" onClick={() => setAiOpen(true)}>Explain blockers</button>
        </div>

        <section className="panel bast-matrix-panel">
          <div className="panel-title-row"><div><h2>Monthly readiness matrix</h2><span>{rows.length} active talents</span></div></div>
          <div className="toolbar bast-toolbar">
            <div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search BAST readiness" /></div>
            <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as StateFilter)} aria-label="Filter BAST readiness by state">
              <option value="all">All states</option>
              <option value="complete">Ready</option>
              <option value="incomplete">Blocked</option>
              <option value="needs_review">Needs review</option>
            </select>
            <select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value as TeamFilter)} aria-label="Filter BAST readiness by team">
              <option value="all">All teams</option>
              <option value="Developer">Developer</option>
              <option value="IoT Operations">IoT Operations</option>
            </select>
          </div>

          {filtered.length === 0 ? <div className="empty-state">No talents match this readiness view.</div> : null}

          <div className="desktop-table-wrap">
            <table className="data-table bast-table">
              <thead><tr><th>Talent</th><th>Attendance</th><th>Timesheet</th><th>Task</th><th>Evidence</th><th>Overall</th><th>Blockers</th><th aria-label="Open" /></tr></thead>
              <tbody>{filtered.map((item) => (
                <tr key={item.employee_id} onClick={() => setSelected(item)}>
                  <td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td>
                  <td><StatusBadge state={item.checks.attendance.state} compact /></td>
                  <td><StatusBadge state={item.checks.timesheet.state} compact /></td>
                  <td><StatusBadge state={item.checks.task.state} compact /></td>
                  <td><StatusBadge state={item.checks.evidence.state} compact /></td>
                  <td><StatusBadge state={item.overall_state} compact /></td>
                  <td><span className="bast-blocker-text">{firstBlockerLabel(item)}{item.issueCount > 0 ? ` · ${item.issueCount} issues` : ""}</span></td>
                  <td><button className="row-open" type="button" aria-label={`Open BAST readiness for ${item.name}`}><ChevronIcon /></button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>

          <div className="mobile-operational-list bast-mobile-list">
            {filtered.map((item) => (
              <button className="mobile-readiness-row bast-mobile-row" type="button" key={item.employee_id} onClick={() => setSelected(item)}>
                <div className="mobile-readiness-head"><div><strong>{item.name}</strong><span>{item.nrp} · {item.role}</span></div><StatusBadge state={item.overall_state} compact /></div>
                <div className="bast-mobile-checks"><span>Attendance <StatusBadge state={item.checks.attendance.state} compact /></span><span>Timesheet <StatusBadge state={item.checks.timesheet.state} compact /></span><span>Task <StatusBadge state={item.checks.task.state} compact /></span><span>Evidence <StatusBadge state={item.checks.evidence.state} compact /></span></div>
                <div className="bast-mobile-blocker">{firstBlockerLabel(item)}{item.issueCount > 0 ? ` · ${item.issueCount} issues` : ""}</div>
                <ChevronIcon className="mobile-chevron" />
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className={`drawer-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`detail-drawer ${selected ? "open" : ""}`} aria-hidden={!selected}>
        {selected ? <>
          <div className="drawer-header"><div><span>{selected.role}</span><h2>{selected.name}</h2><p>{selected.nrp}</p></div><button className="icon-button" type="button" aria-label="Close BAST details" onClick={() => setSelected(null)}><CloseIcon /></button></div>
          <div className="drawer-body">
            <div className="drawer-overall"><span>BAST readiness</span><StatusBadge state={selected.overall_state} /></div>
            <h3>Completion checks</h3>
            {([['Attendance', selected.checks.attendance], ['Timesheet', selected.checks.timesheet], ['Task', selected.checks.task], ['Evidence', selected.checks.evidence]] as const).map(([label, check]) => <div className="bast-check-row" key={label}><span>{label}</span><StatusBadge state={check.state} compact /><strong>{check.issue_count}</strong><small>issues</small></div>)}
            <div className="bast-drawer-blockers"><span>Blocker domains</span><strong>{firstBlockerLabel(selected)}</strong></div>
          </div>
          <div className="drawer-actions bast-drawer-actions"><button className="secondary-button" type="button" onClick={() => explainTalent(selected)}><SparkleIcon />Explain blockers</button><button className="primary-button" type="button" onClick={() => { setSelected(null); onOpenTalent(selected.nrp); }}>Open Talent 360</button></div>
        </> : null}
      </aside>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>Grounded in current readiness facts</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}>
          <label htmlFor="bast-ai-question">Question</label>
          <textarea id="bast-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} />
          <button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}>{aiLoading ? "Thinking…" : "Ask"}</button>
          <div className="ai-safety-note">AI explains deterministic readiness; generation stays deterministic and template-driven.</div>
          {aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now. Readiness data above remains valid.</div> : null}
          {aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}
        </form>
      </section>
    </WorkspaceFrame>
  );
}
