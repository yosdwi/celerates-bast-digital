import { useState } from "react";
import type { FormEvent } from "react";
import { askCommandCenter } from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import { CloseIcon, ExternalIcon, SparkleIcon } from "../components/Icons";
import WorkflowSettings from "../components/WorkflowSettings";
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
        <div className="page-heading"><div><h1>Settings</h1><p>Workflow authorization, routing, and operating boundaries</p></div></div>

        <WorkflowSettings session={session} />

        <div className="settings-grid">
          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Workspace</h2><span>Current session behavior</span></div></div><dl><div><dt>Timezone</dt><dd>{session.timezone}</dd></div><div><dt>Identity</dt><dd>{session.user.name}</dd></div><div><dt>Role</dt><dd>{session.user.role}</dd></div><div><dt>Environment</dt><dd>TalentOps Production</dd></div></dl><p>Login credentials remain in NocoDB. Workflow permissions live in the Digital BAST backend and are not inferred from a WhatsApp number.</p></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>AI behavior</h2><span>Guardrails used across TalentOps</span></div></div><ul><li>AI explains, compares, summarizes, and drafts from deterministic facts.</li><li>AI never grants permissions, approves requests, or calculates readiness.</li><li>Button and free-text actions converge on typed workflow services.</li><li>AI unavailability does not invalidate deterministic workflow data.</li></ul></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Data Workspace</h2><span>Manual record correction boundary</span></div></div><p>NocoDB V2 remains the Data Workspace for record browse/edit and manual correction against the same PostgreSQL rows. TalentOps intentionally does not duplicate those CRUD screens.</p><div className="settings-status">Raw attendance timestamps remain client-owned and immutable in the approval flow</div></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>BAST controls</h2><span>Preview, readiness gate, and audited final generation</span></div></div><p>BAST Readiness now owns the production generation gate. Preview is available for investigation; Final requires readiness unless an authorized operator explicitly force-generates with an audit reason.</p><button className="secondary-button" type="button" onClick={() => onNavigate("/admin/talentops/bast-readiness")}>Open BAST Readiness</button></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>Legacy report tools</h2><span>Existing admin utilities</span></div></div><p>Legacy report tooling remains available during transition. The production BAST workflow should use the readiness-gated TalentOps path.</p><a className="secondary-button settings-link" href="/admin/"><ExternalIcon />Open current report tools</a></section>

          <section className="panel settings-card"><div className="panel-title-row"><div><h2>System signals</h2><span>Operational visibility</span></div></div><p>Use System &amp; Sync for runtime probes and source-ingest observations. Health labels are derived only from real endpoints and observed timestamps.</p><button className="secondary-button" type="button" onClick={() => onNavigate("/admin/talentops/system-sync")}>Open System &amp; Sync</button></section>
        </div>

        <div className="settings-boundary"><strong>Authorization boundary:</strong> Admin provisions PMO access. PMO cannot self-promote, add another PMO, or gain permissions by linking a phone number.</div>
      </div>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>AI cannot modify settings</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="settings-ai-question">Question</label><textarea id="settings-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}><SparkleIcon />{aiLoading ? "Thinking…" : "Ask"}</button><div className="ai-safety-note">AI is informational here and cannot change runtime configuration, roles, permissions, or approval state.</div>{aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now.</div> : null}{aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
