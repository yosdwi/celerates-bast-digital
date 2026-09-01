import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { getRuntimeHealth } from "../api/health";
import type { HealthProbe } from "../api/health";
import { askCommandCenter, getWhatsAppStatus } from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession, WhatsAppStatus } from "../api/types";
import { CloseIcon, RefreshIcon, SparkleIcon, SyncIcon } from "../components/Icons";
import WorkspaceFrame from "../components/WorkspaceFrame";
import { sourceAge } from "../domain/insights";

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
}

function ProbeRow({ label, probe }: { label: string; probe: HealthProbe | null }) {
  const status = probe ? probe.status : "checking";
  const ok = probe?.ok === true;
  return <div className="system-probe-row"><span className={`system-dot ${ok ? "healthy" : probe ? "unhealthy" : "unknown"}`} /><div><strong>{label}</strong><span>{status}</span></div><div>{probe?.httpStatus ? `HTTP ${probe.httpStatus}` : probe ? "No response" : "Checking"}</div></div>;
}

export default function SystemSyncPage({ session, data, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [live, setLive] = useState<HealthProbe | null>(null);
  const [ready, setReady] = useState<HealthProbe | null>(null);
  const [whatsapp, setWhatsapp] = useState<WhatsAppStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("Summarize the observed source-ingest state and explain what PMO can safely conclude from it.");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  async function refreshHealth() {
    if (loading) return;
    setLoading(true);
    try {
      const result = await getRuntimeHealth();
      setLive(result.live);
      setReady(result.ready);
    } finally {
      setLoading(false);
    }
  }

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

  useEffect(() => { void refreshHealth(); }, []);

  // Meta hosts the WhatsApp connection. Poll only the gateway's configuration
  // and readiness signal; there is no linked-device QR or pairing lifecycle.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const result = await getWhatsAppStatus();
        if (!cancelled) setWhatsapp(result);
      } catch {
        if (!cancelled) setWhatsapp({ connection: "unavailable", me: "", provider: "meta_cloud_api" });
      }
    }
    void poll();
    const interval = setInterval(() => void poll(), 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const observedSources = data.sources.filter((source) => source.last_success_at !== null).length;

  return (
    <WorkspaceFrame session={session} active="system" attentionCount={data.summary.need_attention} search={search} onSearch={setSearch} onNavigate={onNavigate} onAskAi={() => setAiOpen(true)}>
      <div className="content system-sync-page">
        <div className="page-heading"><div><h1>System &amp; Sync</h1><p>Runtime probes and source-ingest observations</p></div><button className="secondary-button" type="button" disabled={loading} onClick={() => void refreshHealth()}><RefreshIcon />{loading ? "Checking" : "Refresh"}</button></div>

        <div className="summary-strip system-summary" aria-label="System and Sync summary">
          <div className="summary-item"><div className="summary-label">Application live</div><div className="summary-value">{live ? (live.ok ? "Yes" : "No") : "—"}</div><div className="summary-meta">/health/live</div></div>
          <div className="summary-item"><div className="summary-label">Application ready</div><div className="summary-value">{ready ? (ready.ok ? "Yes" : "No") : "—"}</div><div className="summary-meta">Sessions, auth, backend readiness</div></div>
          <div className="summary-item"><div className="summary-label">Sources observed</div><div className="summary-value">{observedSources} / {data.sources.length}</div><div className="summary-meta">Successful ingest timestamps</div></div>
          <div className="summary-item"><div className="summary-label">Sync SLA</div><div className="summary-value">Not set</div><div className="summary-meta">No threshold is inferred</div></div>
        </div>

        <div className="system-grid">
          <section className="panel"><div className="panel-title-row"><div><h2>Runtime health</h2><span>Existing FastAPI health endpoints</span></div></div><div className="system-probe-list"><ProbeRow label="Liveness" probe={live} /><ProbeRow label="Readiness" probe={ready} /></div><div className="system-note">Readiness is the application-level result returned by the existing backend. This screen does not reinterpret it as separate PostgreSQL, Redis, or AI health.</div></section>

          <section className="panel"><div className="panel-title-row"><div><h2>Source ingest</h2><span>Last successful server ingest</span></div></div><div className="system-source-list">{data.sources.map((source) => <div className="system-source-row" key={source.source_key}><span className={`system-dot ${source.last_success_at ? "healthy" : "unknown"}`} /><div><strong>{source.label}</strong><span>{source.last_success_at ? new Date(source.last_success_at).toLocaleString() : "No successful ingest observed"}</span></div><strong>{sourceAge(source)}</strong></div>)}</div><div className="system-note">A timestamp proves only that a successful ingest was observed. It is not automatically classified as stale without an explicit SLA.</div></section>

          <section className="panel"><div className="panel-title-row"><div><h2>WhatsApp Cloud API</h2><span>Official Meta gateway status</span></div></div><div className="system-probe-row"><span className={`system-dot ${whatsapp?.connection === "connected" ? "healthy" : whatsapp ? "unhealthy" : "unknown"}`} /><div><strong>{whatsapp ? whatsapp.connection : "checking"}</strong><span>{whatsapp?.me || "Phone Number ID belum dikonfigurasi"}</span></div><div>{whatsapp?.connection === "connected" ? "Meta configured" : "Needs attention"}</div></div><div className="system-note">Meta mengelola koneksi WhatsApp. Tidak ada QR, pairing code, linked device, atau session file di server Digital BAST.</div></section>
        </div>

        <section className="panel system-boundary-panel"><div className="panel-title-row"><div><h2>Operational boundaries</h2><span>What this page can and cannot claim</span></div></div><div className="system-boundaries"><div><SyncIcon /><strong>Observed</strong><span>FastAPI liveness/readiness and last successful ingest timestamps.</span></div><div><SyncIcon /><strong>Not inferred</strong><span>Database-specific health, queue depth, Ollama availability, ingest SLA, or source lag thresholds unless exposed by a real backend signal.</span></div></div></section>
      </div>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>Grounded in Command Center and ingest facts</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="system-ai-question">Question</label><textarea id="system-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}><SparkleIcon />{aiLoading ? "Thinking…" : "Ask"}</button><div className="ai-safety-note">AI may explain observed source facts. It must not invent an SLA, database-specific health, queue depth, or Ollama status that is not exposed by the backend.</div>{aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now. Runtime probes and observed timestamps remain valid.</div> : null}{aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
