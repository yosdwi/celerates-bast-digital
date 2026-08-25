import { useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter } from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import { CloseIcon, ExternalIcon, SparkleIcon } from "../components/Icons";
import WorkspaceFrame from "../components/WorkspaceFrame";

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
}

export default function SettingsPage({ session, data, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Explain the current TalentOps operating boundaries for PMO users.");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

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

  return (
    <WorkspaceFrame session={session} active="settings" attentionCount={data.summary.need_attention} search={search} onSearch={setSearch} onNavigate={onNavigate} onAskAi={() => setAiOpen(true)}>
      <div className="content settings-page">
        <div className="page-heading"><div><h1>Settings</h1><p>Current workspace policy and integration boundaries</p></div></div>

        <div className="settings-grid">
          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Workspace</h2><span>Current session behavior</span></div></div><dl><div><dt>Timezone</dt><dd>{session.timezone}</dd></div><div><dt>Identity</dt><dd>{session.user.name}</dd></div><div><dt>Environment</dt><dd>TalentOps Production</dd></div></dl><p>These values are displayed from the current session/runtime. This page does not create a second account or role-management system.</p></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>AI behavior</h2><span>Guardrails used across TalentOps</span></div></div><ul><li>AI explains, compares, summarizes, and drafts from deterministic facts.</li><li>AI does not calculate readiness or invent missing business metrics.</li><li>Follow-up stays draft-only until an explicit send workflow is implemented.</li><li>AI unavailability does not invalidate deterministic readiness data.</li></ul></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Data Workspace</h2><span>Manual record correction boundary</span></div></div><p>NocoDB V2 remains the Data Workspace for record browse/edit and manual correction against the same PostgreSQL rows. TalentOps intentionally does not duplicate those CRUD screens.</p><div className="settings-status">External workspace · URL is not exposed in the current web contract</div></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Report tools</h2><span>Existing Digital BAST generator</span></div></div><p>Report generation remains in the existing admin surface. BAST Readiness evaluates closing blockers but does not create a second report generator.</p><a className="secondary-button settings-link" href="/admin/"><ExternalIcon />Open current report tools</a></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Notifications</h2><span>No PMO notification preference store yet</span></div></div><p>TalentOps does not currently persist notification channels, acknowledgement state, reminder cadence, or escalation rules. Those controls are intentionally not faked as editable settings.</p><div className="settings-status">Not configured in the current domain model</div></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>System signals</h2><span>Operational visibility</span></div></div><p>Use System &amp; Sync for runtime probes and source-ingest observations. Health labels are derived only from real endpoints and observed timestamps.</p><button className="secondary-button" type="button" onClick={() => onNavigate("/admin/talentops/system-sync")}>Open System &amp; Sync</button></section>
        </div>

        <div className="settings-boundary"><strong>Configuration boundary:</strong> this page documents and exposes current product behavior. It does not persist placeholder preferences that the backend cannot enforce.</div>
      </div>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>AI cannot modify settings</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="settings-ai-question">Question</label><textarea id="settings-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}><SparkleIcon />{aiLoading ? "Thinking…" : "Ask"}</button><div className="ai-safety-note">AI is informational here and cannot change runtime configuration or account settings.</div>{aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now.</div> : null}{aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
