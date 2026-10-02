import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  askCommandCenter,
  askTalent,
  createBastGenerationJob,
  downloadBastDocument,
  getBastGenerationJob,
  getBastReadiness,
  listBastGenerationJobs,
} from "../api/talentops";
import type { BastGenerationJob, BastGenerationMode, BastReportType } from "../api/talentops";
import type {
  AiInvestigation,
  AttentionItem,
  BastReadiness,
  CheckState,
  CommandCenterResponse,
  EmployeeRole,
  OperationalSignal,
  TalentOpsSession,
  TalentReadiness,
} from "../api/types";
import { ChevronIcon, CloseIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import InvestigationCard from "../components/InvestigationCard";
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
  blockers: AttentionItem["blockers"];
  signals: OperationalSignal[];
}

function firstBlockerLabel(row: ReadinessRow): string {
  if (row.overall_state === "complete") return "No blockers";
  return row.blockerDomains.length ? row.blockerDomains.map(domainLabel).join(", ") : "Needs review";
}

function firstIssue(row: ReadinessRow): string | null {
  for (const blocker of row.blockers) {
    const issue = blocker.issues[0];
    if (issue) return issue;
  }
  return null;
}

function historyStatusLabel(status: BastGenerationJob["display_status"]): string {
  if (status === "succeeded") return "Ready";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  if (status === "stale") return "Stale";
  return "Running";
}

function bastFmtElapsed(sec: number): string {
  const mm = Math.floor(sec / 60);
  const ss = sec % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

function bastNotify(title: string, body: string) {
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((permission) => {
        if (permission === "granted") new Notification(title, { body });
      }).catch(() => {});
    }
  } catch {
    // Notification API unavailable (unsupported browser, insecure context) -- silently skip.
  }
}

function signalMeta(signal: OperationalSignal): string | null {
  const parts: string[] = [];
  if (signal.dates.length) parts.push(signal.dates.join(", "));
  if (signal.task_titles.length) parts.push(signal.task_titles.join(", "));
  return parts.length ? parts.join(" · ") : null;
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
  const [bastGate, setBastGate] = useState<BastReadiness | null>(null);
  const [gateLoading, setGateLoading] = useState(false);
  const [forceOpen, setForceOpen] = useState(false);
  const [forceReason, setForceReason] = useState("");
  const [generationState, setGenerationState] = useState<GenerationState>("idle");
  const [generationMessage, setGenerationMessage] = useState("");
  const [jobs, setJobs] = useState<BastGenerationJob[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [genStartedAt, setGenStartedAt] = useState<number | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    if (generationState !== "generating") {
      setElapsedSec(0);
      return;
    }
    const tickId = window.setInterval(() => {
      setElapsedSec(genStartedAt ? Math.floor((Date.now() - genStartedAt) / 1000) : 0);
    }, 1000);
    return () => window.clearInterval(tickId);
  }, [generationState, genStartedAt]);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiTarget, setAiTarget] = useState<ReadinessRow | null>(null);
  const [aiQuestion, setAiQuestion] = useState(
    "Summarize the current BAST readiness blockers and what PMO should verify first.",
  );
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiInvestigation, setAiInvestigation] = useState<AiInvestigation | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const rows = useMemo<ReadinessRow[]>(() => {
    const attentionByNrp = new Map(data.attention.map((item) => [item.nrp, item]));
    const signalsByNrp = new Map<string, OperationalSignal[]>();
    for (const signal of data.signals ?? []) {
      if (!signal.nrp) continue;
      const current = signalsByNrp.get(signal.nrp) ?? [];
      current.push(signal);
      signalsByNrp.set(signal.nrp, current);
    }
    return data.readiness.map((item) => {
      const attention = attentionByNrp.get(item.nrp);
      const blockers = attention?.blockers ?? [];
      return {
        ...item,
        blockerDomains: blockers.map((blocker) => blocker.domain),
        issueCount: Object.values(item.checks).reduce((sum, check) => sum + check.issue_count, 0),
        blockers,
        signals: signalsByNrp.get(item.nrp) ?? [],
      };
    });
  }, [data.attention, data.readiness, data.signals]);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filtered = useMemo(
    () => rows.filter((item) => {
      const stateOk = stateFilter === "all" || item.overall_state === stateFilter;
      const teamOk = teamFilter === "all" || item.role === teamFilter;
      const searchOk = !normalizedSearch
        || `${item.name} ${item.nrp} ${item.role}`.toLocaleLowerCase().includes(normalizedSearch);
      return stateOk && teamOk && searchOk;
    }),
    [normalizedSearch, rows, stateFilter, teamFilter],
  );

  const blockedCount = rows.filter((item) => item.overall_state === "incomplete").length;
  const reviewCount = rows.filter((item) => item.overall_state === "needs_review").length;
  const readyCount = rows.filter((item) => item.overall_state === "complete").length;
  const primarySignal = data.signals?.[0] ?? null;

  async function refreshBastGate(reportType = bastReportType) {
    setGateLoading(true);
    try {
      setBastGate(await getBastReadiness(data.period, reportType));
    } catch (error) {
      setBastGate(null);
      setGenerationState("error");
      setGenerationMessage(error instanceof Error ? error.message : "BAST readiness gate unavailable.");
    } finally {
      setGateLoading(false);
    }
  }

  useEffect(() => {
    void refreshBastGate(bastReportType);
  }, [bastReportType, data.period.year, data.period.month]);

  async function refreshJobs() {
    try {
      setJobs(await listBastGenerationJobs(10));
    } catch {
      // History is a convenience view alongside the gate card -- a failed
      // fetch here shouldn't block Preview/Final Generate.
    } finally {
      setJobsLoading(false);
    }
  }

  useEffect(() => {
    void refreshJobs();
    const intervalId = window.setInterval(() => void refreshJobs(), 15_000);
    return () => window.clearInterval(intervalId);
  }, []);

  async function pollJob(jobId: string): Promise<BastGenerationJob> {
    let job = await getBastGenerationJob(jobId);
    while (job.display_status === "pending" || job.display_status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 4000));
      job = await getBastGenerationJob(jobId);
    }
    if (job.display_status !== "succeeded") {
      throw new Error(
        job.error_message
          || (job.display_status === "stale"
            ? "BAST generation appears to have stalled — try again."
            : "BAST generation failed."),
      );
    }
    return job;
  }

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

  async function submitBastGeneration(mode: BastGenerationMode, force = false) {
    if (generationState === "generating") return;
    if (force && !forceReason.trim()) {
      setGenerationState("error");
      setGenerationMessage("Force Final requires an audit reason.");
      return;
    }
    setGenerationState("generating");
    setGenerationMessage("");
    setGenStartedAt(Date.now());
    try {
      if (Notification.permission === "default") Notification.requestPermission().catch(() => {});
    } catch {
      // Notification API unavailable (unsupported browser, insecure context) -- silently skip.
    }
    try {
      const created = await createBastGenerationJob(
        session.csrf_token,
        data.period,
        bastReportType,
        mode,
        force,
        forceReason,
      );
      const finished = await pollJob(created.id);
      const generated = await downloadBastDocument(
        { year: finished.year, month: finished.month },
        finished.report_type,
      );
      triggerDownload(generated.blob, generated.filename);
      setGenerationState("success");
      const message = `${generated.filename} generated as ${finished.mode}${finished.forced ? " · forced with audit" : ""}.`;
      setGenerationMessage(message);
      bastNotify("BAST generation complete", `${generated.filename} is ready and downloading.`);
      setForceOpen(false);
      setForceReason("");
      await refreshBastGate();
      await refreshJobs();
    } catch (error) {
      const message = error instanceof Error ? error.message : "BAST generation failed.";
      setGenerationState("error");
      setGenerationMessage(message);
      bastNotify("BAST generation failed", message);
      await refreshBastGate();
      await refreshJobs();
    }
  }

  function openGlobalInvestigation() {
    setAiTarget(null);
    setAiQuestion("Summarize the current BAST readiness blockers and what PMO should verify first.");
    setAiAnswer(null);
    setAiInvestigation(null);
    setAiUnavailable(false);
    setAiOpen(true);
  }

  function investigateTalent(item: ReadinessRow) {
    setSelected(null);
    setAiTarget(item);
    setAiQuestion(`Why is ${item.name} blocked for BAST and what should PMO verify first?`);
    setAiAnswer(null);
    setAiInvestigation(null);
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
      onAskAi={openGlobalInvestigation}
    >
      <div className="content bast-readiness-page">
        <div className="page-heading bast-heading">
          <div><h1>BAST Readiness</h1><p>{data.period.label} · preview anytime, final generation is readiness-gated</p></div>
          <div className="bast-generation">
            <div className="bast-generation-controls">
              <select
                aria-label="BAST report type"
                value={bastReportType}
                disabled={generationState === "generating"}
                onChange={(event) => { setBastReportType(event.target.value as BastReportType); setForceOpen(false); }}
              >
                <option value="developer">Developer</option>
                <option value="iotoperation">IoT Operations</option>
              </select>
              <button className="secondary-button" type="button" disabled={generationState === "generating" || gateLoading} onClick={() => void submitBastGeneration("preview")}>Preview PDF</button>
              <button className="primary-button" type="button" disabled={generationState === "generating" || gateLoading || !bastGate?.ready} onClick={() => void submitBastGeneration("final")}>{generationState === "generating" ? "Generating…" : "Final Generate"}</button>
            </div>
            {generationState === "generating" ? (
              <div className="bast-generation-status generating" role="status">
                <strong>Sedang memproses… {bastFmtElapsed(elapsedSec)}</strong>
                <p>
                  Laporan besar (mis. IoT Operations) bisa memakan waktu hingga ~15 menit. Anda boleh
                  meninggalkan halaman ini — hasil akan otomatis terunduh, dan tetap muncul di Riwayat
                  Generate di bawah untuk diunduh ulang kapan saja.
                </p>
              </div>
            ) : null}
            {generationState === "success" ? <div className="bast-generation-status success" role="status">{generationMessage}</div> : null}
            {generationState === "error" ? <div className="bast-generation-status error" role="alert">{generationMessage}</div> : null}
          </div>
        </div>

        <div className={`bast-gate-card ${bastGate?.ready ? "ready" : "blocked"}`}>
          {gateLoading ? <strong>Checking final-generation gate…</strong> : bastGate ? <>
            <strong>{bastGate.ready ? "Final generation ready" : "Final generation blocked"}</strong>
            <div className="cell-muted">{bastGate.role} · {bastGate.ready_talents}/{bastGate.total_talents} talents ready · {bastGate.blockers.length} blocker records</div>
            {!bastGate.ready ? <div className="approval-inline-actions">
              <button className="secondary-button" type="button" onClick={() => setForceOpen((open) => !open)}>Force Final…</button>
              <span className="cell-muted">Requires permission + mandatory audit reason.</span>
            </div> : null}
            {forceOpen ? <div className="bast-force-box">
              <label htmlFor="force-bast-reason">Force reason</label>
              <textarea id="force-bast-reason" rows={3} maxLength={500} value={forceReason} onChange={(event) => setForceReason(event.target.value)} placeholder="Why must Final BAST be generated before readiness is complete?" />
              <div className="approval-inline-actions"><button className="secondary-button" type="button" onClick={() => { setForceOpen(false); setForceReason(""); }}>Cancel</button><button className="primary-button" type="button" disabled={!forceReason.trim() || generationState === "generating"} onClick={() => void submitBastGeneration("final", true)}>Force Final Generate</button></div>
            </div> : null}
          </> : <strong>BAST readiness gate unavailable.</strong>}
        </div>

        <section className="panel bast-history-panel">
          <div className="panel-title-row"><div><h2>Generation history</h2><span>Last {jobs.length} run{jobs.length === 1 ? "" : "s"}</span></div></div>
          {jobsLoading ? <div className="empty-state">Memuat…</div> : null}
          {!jobsLoading && jobs.length === 0 ? <div className="empty-state">Belum ada riwayat generate.</div> : null}
          <div className="bast-history-list">
            {jobs.map((job) => (
              <div className="bast-history-item" key={job.id}>
                <div className="bast-history-item-main">
                  <strong>{job.report_type}</strong>
                  <span className="cell-muted">
                    {job.year}-{String(job.month).padStart(2, "0")} · {job.mode}{job.forced ? " · forced" : ""}
                  </span>
                </div>
                <div className={`bast-history-status ${job.display_status}`}>
                  <span className="bast-history-status-dot" aria-hidden="true" />
                  {historyStatusLabel(job.display_status)}
                </div>
                <div className="cell-muted">{new Date(job.created_at).toLocaleString("id-ID")}</div>
                {job.display_status === "succeeded" ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void downloadBastDocument({ year: job.year, month: job.month }, job.report_type).then((file) => triggerDownload(file.blob, file.filename))}
                  >
                    Download
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <div className="summary-strip bast-summary" aria-label="BAST readiness summary">
          <div className="summary-item"><div className="summary-label">Ready</div><div className="summary-value">{readyCount} / {rows.length}</div><div className="summary-meta">{readinessPercent(readyCount, rows.length)}</div></div>
          <div className="summary-item"><div className="summary-label">Blocked</div><div className="summary-value">{blockedCount}</div><div className="summary-meta">Incomplete readiness</div></div>
          <div className="summary-item"><div className="summary-label">Needs review</div><div className="summary-value">{reviewCount}</div><div className="summary-meta">Manual review required</div></div>
          <div className="summary-item"><div className="summary-label">Evidence ready</div><div className="summary-value">{data.summary.evidence_ready} / {data.summary.active_talents}</div><div className="summary-meta">Same deterministic rules</div></div>
        </div>

        <div className="ai-insight-strip bast-ai-strip">
          <span className="ai-insight-icon"><SparkleIcon /></span>
          <div><strong>{primarySignal?.title ?? "Readiness stays deterministic."}</strong>{primarySignal ? ` · ${primarySignal.summary}` : " · Investigation can synthesize blocker facts, but it cannot change readiness."}</div>
          <button type="button" onClick={openGlobalInvestigation}>Investigate BAST blockers</button>
        </div>

        <section className="panel bast-matrix-panel">
          <div className="panel-title-row"><div><h2>Monthly readiness matrix</h2><span>{rows.length} active talents</span></div></div>
          <div className="toolbar bast-toolbar">
            <div className="panel-search"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search talent or NRP" aria-label="Search BAST readiness" /></div>
            <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as StateFilter)} aria-label="Filter BAST readiness by state"><option value="all">All states</option><option value="complete">Ready</option><option value="incomplete">Blocked</option><option value="needs_review">Needs review</option></select>
            <select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value as TeamFilter)} aria-label="Filter BAST readiness by team"><option value="all">All teams</option><option value="Developer">Developer</option><option value="IoT Operations">IoT Operations</option></select>
          </div>

          {filtered.length === 0 ? <div className="empty-state">No talents match this readiness view.</div> : null}
          <div className="desktop-table-wrap">
            <table className="data-table bast-table">
              <thead><tr><th>Talent</th><th>Attendance</th><th>Timesheet</th><th>Task</th><th>Evidence</th><th>Overall</th><th>Blockers</th><th aria-label="Open" /></tr></thead>
              <tbody>{filtered.map((item) => {
                const issue = firstIssue(item);
                return <tr key={item.employee_id} onClick={() => setSelected(item)}><td><div className="talent-name">{item.name}</div><div className="cell-muted">{item.nrp} · {item.role}</div></td><td><StatusBadge state={item.checks.attendance.state} compact /></td><td><StatusBadge state={item.checks.timesheet.state} compact /></td><td><StatusBadge state={item.checks.task.state} compact /></td><td><StatusBadge state={item.checks.evidence.state} compact /></td><td><StatusBadge state={item.overall_state} compact /></td><td><div className="talent-name">{firstBlockerLabel(item)}{item.issueCount > 0 ? ` · ${item.issueCount}` : ""}</div><span className="bast-blocker-text">{issue ?? (item.signals[0]?.summary || "No blocker detail")}</span></td><td><button className="row-open" type="button" aria-label={`Open BAST readiness for ${item.name}`}><ChevronIcon /></button></td></tr>;
              })}</tbody>
            </table>
          </div>

          <div className="mobile-operational-list bast-mobile-list">
            {filtered.map((item) => <button className="mobile-readiness-row bast-mobile-row" type="button" key={item.employee_id} onClick={() => setSelected(item)}><div className="mobile-readiness-head"><div><strong>{item.name}</strong><span>{item.nrp} · {item.role}</span></div><StatusBadge state={item.overall_state} compact /></div><div className="bast-mobile-checks"><span>Attendance <StatusBadge state={item.checks.attendance.state} compact /></span><span>Timesheet <StatusBadge state={item.checks.timesheet.state} compact /></span><span>Task <StatusBadge state={item.checks.task.state} compact /></span><span>Evidence <StatusBadge state={item.checks.evidence.state} compact /></span></div><div className="bast-mobile-blocker"><strong>{firstBlockerLabel(item)}</strong>{firstIssue(item) ? ` · ${firstIssue(item)}` : item.signals[0] ? ` · ${item.signals[0].summary}` : ""}</div><ChevronIcon className="mobile-chevron" /></button>)}
          </div>
        </section>
      </div>

      <div className={`drawer-overlay ${selected ? "open" : ""}`} onClick={() => setSelected(null)} />
      <aside className={`detail-drawer ${selected ? "open" : ""}`} aria-hidden={!selected}>
        {selected ? <><div className="drawer-header"><div><span>{selected.role}</span><h2>{selected.name}</h2><p>{selected.nrp}</p></div><button className="icon-button" type="button" aria-label="Close BAST details" onClick={() => setSelected(null)}><CloseIcon /></button></div><div className="drawer-body"><div className="drawer-overall"><span>BAST readiness</span><StatusBadge state={selected.overall_state} /></div><h3>Completion checks</h3>{([['Attendance', selected.checks.attendance], ['Timesheet', selected.checks.timesheet], ['Task', selected.checks.task], ['Evidence', selected.checks.evidence]] as const).map(([label, check]) => <div className="bast-check-row" key={label}><span>{label}</span><StatusBadge state={check.state} compact /><strong>{check.issue_count}</strong><small>issues</small></div>)}<h3>Operational signals</h3>{selected.signals.length ? selected.signals.map((signal, index) => <div className="bast-drawer-blockers" key={`${signal.kind}-${index}`}><span>{signal.domains.map(domainLabel).join(" → ") || "Readiness signal"}</span><strong>{signal.title}</strong><p className="cell-muted">{signal.summary}</p>{signalMeta(signal) ? <small className="cell-muted">{signalMeta(signal)}</small> : null}</div>) : <div className="empty-state">No additional operational signal for this talent.</div>}<h3>Blocker facts</h3>{selected.blockers.length ? selected.blockers.map((blocker) => <div className="blocker-card" key={blocker.domain}><div className="blocker-head"><strong>{domainLabel(blocker.domain)}</strong><StatusBadge state={blocker.state} compact /></div>{blocker.issues.length ? <ul>{blocker.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : <p>No detailed issue text was returned.</p>}</div>) : <div className="empty-state">No blocker facts are present for this readiness state.</div>}</div><div className="drawer-actions bast-drawer-actions"><button className="secondary-button" type="button" onClick={() => investigateTalent(selected)}><SparkleIcon />Investigate blockers</button><button className="primary-button" type="button" onClick={() => { setSelected(null); onOpenTalent(selected.nrp); }}>Open Talent 360</button></div></> : null}
      </aside>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>{aiTarget ? `Grounded in ${aiTarget.name}'s date-level facts` : "Grounded in current BAST readiness facts"}</span><h2>Investigate BAST readiness</h2></div><button className="icon-button" type="button" aria-label="Close investigation" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><div className="filter-chips" role="group" aria-label="BAST investigation prompts">{aiTarget ? <><button type="button" onClick={() => setAiQuestion(`Why is ${aiTarget.name} blocked for BAST and what should PMO verify first?`)}>Why blocked?</button><button type="button" onClick={() => setAiQuestion("Which dates should PMO verify first, and are Attendance and Timesheet related?")}>Related dates</button><button type="button" onClick={() => setAiQuestion("Which Closed tasks still have missing Evidence?")}>Missing evidence</button></> : <><button type="button" onClick={() => setAiQuestion("Which BAST blockers affect the most current readiness domains?")}>Top blockers</button><button type="button" onClick={() => setAiQuestion("What cross-domain readiness patterns should PMO verify first?")}>Cross-domain</button><button type="button" onClick={() => setAiQuestion("What should PMO verify first before the next BAST generation?")}>Next review</button></>}</div><label htmlFor="bast-ai-question">Question</label><textarea id="bast-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}>{aiLoading ? "Investigating…" : "Investigate"}</button><div className="ai-safety-note">Readiness stays deterministic. Investigation can only synthesize server-owned facts and evidence.</div>{aiUnavailable ? <div className="ai-unavailable">AI investigation is unavailable. Deterministic readiness and blocker facts remain valid.</div> : null}{aiInvestigation ? <InvestigationCard investigation={aiInvestigation} /> : aiAnswer ? <div className="ai-answer"><span>Finding</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
