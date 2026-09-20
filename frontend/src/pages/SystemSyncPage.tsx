import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { getRuntimeHealth } from "../api/health";
import type { HealthProbe } from "../api/health";
import { askCommandCenter } from "../api/talentops";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import {
  controlWhatsAppRecovery,
  getWhatsAppOperations,
  startControlledWhatsAppPairing,
  unavailableWhatsAppOperations,
} from "../api/whatsapp-ops";
import type { WhatsAppOperationsStatus } from "../api/whatsapp-ops";
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

function whatsappDisplay(status: WhatsAppOperationsStatus | null): {
  label: string;
  detail: string;
  tone: "healthy" | "unhealthy" | "unknown";
} {
  if (!status) return { label: "Checking", detail: "Membaca status bridge", tone: "unknown" };
  if (status.ready) {
    return { label: "Terhubung", detail: status.me || "WhatsApp siap mengirim pesan", tone: "healthy" };
  }
  if (
    status.operator_action_required ||
    !status.owner_acquired ||
    !status.storage_healthy ||
    !status.receipt_store_healthy ||
    status.recovery_state === "blocked" ||
    status.recovery_state === "cooldown"
  ) {
    return {
      label: "Perlu tindakan",
      detail: status.operator_reason || status.recovery_reason || "Periksa detail operasional",
      tone: "unhealthy",
    };
  }
  if (status.recovery_paused) {
    return { label: "Dijeda", detail: "Auto recovery sedang dijeda operator", tone: "unknown" };
  }
  if (["starting", "recovering", "observing"].includes(status.recovery_state)) {
    return {
      label: "Sedang pulih",
      detail: status.recovery_reason || status.connection,
      tone: "unknown",
    };
  }
  return { label: "Tidak terhubung", detail: status.connection, tone: "unhealthy" };
}

function timestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function SystemSyncPage({ session, data, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [live, setLive] = useState<HealthProbe | null>(null);
  const [ready, setReady] = useState<HealthProbe | null>(null);
  const [whatsapp, setWhatsapp] = useState<WhatsAppOperationsStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [whatsappBusy, setWhatsappBusy] = useState(false);
  const [whatsappAction, setWhatsappAction] = useState<string | null>(null);
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

  async function refreshWhatsApp() {
    try {
      setWhatsapp(await getWhatsAppOperations());
    } catch {
      setWhatsapp(unavailableWhatsAppOperations());
    }
  }

  async function runWhatsAppControl(action: "pause" | "resume" | "reconnect") {
    if (whatsappBusy) return;
    setWhatsappBusy(true);
    setWhatsappAction(null);
    try {
      const result = await controlWhatsAppRecovery(session.csrf_token, action);
      setWhatsappAction(result.accepted ? "Perintah diterima." : `Tidak dijalankan: ${result.reason}`);
      await refreshWhatsApp();
    } catch {
      setWhatsappAction("Perintah tidak dapat dijalankan. Periksa izin dan status bridge.");
    } finally {
      setWhatsappBusy(false);
    }
  }

  async function startPairing() {
    if (whatsappBusy) return;
    setWhatsappBusy(true);
    setWhatsappAction(null);
    try {
      const result = await startControlledWhatsAppPairing(session.csrf_token);
      setWhatsappAction(result.accepted ? "Pairing terkontrol dimulai." : `Pairing tidak dimulai: ${result.reason}`);
      await refreshWhatsApp();
    } catch {
      setWhatsappAction("Pairing tidak dapat dimulai. Periksa izin admin dan status bridge.");
    } finally {
      setWhatsappBusy(false);
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

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const result = await getWhatsAppOperations();
        if (!cancelled) setWhatsapp(result);
      } catch {
        if (!cancelled) setWhatsapp(unavailableWhatsAppOperations());
      }
    }
    void poll();
    const interval = setInterval(() => void poll(), 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const observedSources = data.sources.filter((source) => source.last_success_at !== null).length;
  const waDisplay = whatsappDisplay(whatsapp);
  const adminPairing = ["owner", "admin"].includes(session.user.role.toLowerCase());
  const pairingVisible = Boolean(
    whatsapp &&
    !whatsapp.ready &&
    (whatsapp.qr_data_url || whatsapp.pairing_code),
  );
  const reconnectSafe = Boolean(
    whatsapp &&
    !whatsapp.ready &&
    !whatsapp.operator_action_required &&
    whatsapp.owner_acquired &&
    whatsapp.storage_healthy &&
    whatsapp.receipt_store_healthy &&
    whatsapp.recovery_state !== "recovering",
  );

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

          <section className="panel">
            <div className="panel-title-row"><div><h2>WhatsApp bot</h2><span>Session, recovery, and durable outbound receipts</span></div><button className="icon-button" type="button" aria-label="Refresh WhatsApp" disabled={whatsappBusy} onClick={() => void refreshWhatsApp()}><RefreshIcon /></button></div>
            <div className="system-probe-row"><span className={`system-dot ${waDisplay.tone}`} /><div><strong>{waDisplay.label}</strong><span>{waDisplay.detail}</span></div><div>{whatsapp?.me || "Belum terpasang"}</div></div>
            {whatsapp ? <div className="system-source-list">
              <div className="system-source-row"><span className={`system-dot ${whatsapp.owner_acquired ? "healthy" : "unhealthy"}`} /><div><strong>Session owner</strong><span>{whatsapp.owner_acquired ? "Single owner acquired" : "Owner conflict / lease unavailable"}</span></div><strong>{whatsapp.owner_acquired ? "OK" : "BLOCKED"}</strong></div>
              <div className="system-source-row"><span className={`system-dot ${whatsapp.storage_healthy ? "healthy" : "unhealthy"}`} /><div><strong>Auth storage</strong><span>{whatsapp.storage_healthy ? "Writable with safety checks" : whatsapp.storage_reasons.join(", ") || "Unsafe"}</span></div><strong>{whatsapp.storage_healthy ? "OK" : "CHECK"}</strong></div>
              <div className="system-source-row"><span className={`system-dot ${whatsapp.receipt_store_healthy ? "healthy" : "unhealthy"}`} /><div><strong>Outbound receipts</strong><span>Sent {whatsapp.receipt_sent} · UNKNOWN {whatsapp.receipt_unknown} · in-flight {whatsapp.receipt_in_flight}</span></div><strong>{whatsapp.receipt_store_healthy ? "OK" : "CHECK"}</strong></div>
            </div> : null}
            {whatsapp ? <div className="system-note">Recovery: <strong>{whatsapp.recovery_state}</strong>{whatsapp.recovery_reason ? ` · ${whatsapp.recovery_reason}` : ""}. Attempts {whatsapp.recovery_attempts}/{whatsapp.recovery_max_attempts}. Last probe {timestamp(whatsapp.last_probe_at)}. Last outbound ack {timestamp(whatsapp.last_ack_at)}.{whatsapp.cooldown_until ? ` Cooldown sampai ${timestamp(whatsapp.cooldown_until)}.` : ""}</div> : null}
            {whatsapp && whatsapp.receipt_unknown > 0 ? <div className="system-note"><strong>UNKNOWN delivery bukan gagal biasa.</strong> Jangan resend blind. Periksa Payroll Follow-up/delivery ledger sebelum tindakan manual.</div> : null}
            <div className="page-actions">
              <button className="secondary-button" type="button" disabled={whatsappBusy || !whatsapp} onClick={() => void runWhatsAppControl(whatsapp?.recovery_paused ? "resume" : "pause")}>{whatsapp?.recovery_paused ? "Resume auto recovery" : "Pause auto recovery"}</button>
              <button className="secondary-button" type="button" disabled={whatsappBusy || !reconnectSafe} onClick={() => void runWhatsAppControl("reconnect")}>Reconnect aman</button>
              {adminPairing && whatsapp?.operator_action_required ? <button className="secondary-button" type="button" disabled={whatsappBusy} onClick={() => void startPairing()}>Mulai pairing</button> : null}
            </div>
            {whatsappAction ? <div className="system-note">{whatsappAction}</div> : null}
            {pairingVisible ? <div className="system-note">{whatsapp?.qr_data_url ? <img src={whatsapp.qr_data_url} alt="QR pairing WhatsApp" width={220} height={220} /> : null}{whatsapp?.pairing_code ? <p>Atau masukkan kode ini di WhatsApp → Tautkan dengan nomor telepon: <strong>{whatsapp.pairing_code}</strong></p> : null}<p>Pairing hanya digunakan saat sesi memang membutuhkan tindakan operator. Auto recovery tidak menghapus LocalAuth.</p></div> : null}
          </section>
        </div>

        <section className="panel system-boundary-panel"><div className="panel-title-row"><div><h2>Operational boundaries</h2><span>What this page can and cannot claim</span></div></div><div className="system-boundaries"><div><SyncIcon /><strong>Observed</strong><span>FastAPI liveness/readiness, source ingest timestamps, WhatsApp bridge readiness, recovery state, owner/storage safety, and durable outbound receipt facts.</span></div><div><SyncIcon /><strong>Not inferred</strong><span>Exactly-once WhatsApp delivery, anti-ban guarantees, automatic safe resend for UNKNOWN outcomes, or database/source SLA that is not exposed by a real backend signal.</span></div></div></section>
      </div>

      <section className={`ai-panel ${aiOpen ? "open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-panel-header"><div><span>Grounded in Command Center and ingest facts</span><h2>Ask AI</h2></div><button className="icon-button" type="button" aria-label="Close AI" onClick={() => setAiOpen(false)}><CloseIcon /></button></div>
        <form className="ai-panel-body" onSubmit={submitAi}><label htmlFor="system-ai-question">Question</label><textarea id="system-ai-question" rows={4} maxLength={1000} value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} /><button className="primary-button" type="submit" disabled={aiLoading || !aiQuestion.trim()}><SparkleIcon />{aiLoading ? "Thinking…" : "Ask"}</button><div className="ai-safety-note">AI may explain observed source facts. It must not invent an SLA, database-specific health, queue depth, or Ollama status that is not exposed by the backend.</div>{aiUnavailable ? <div className="ai-unavailable">AI is unavailable right now. Runtime probes and observed timestamps remain valid.</div> : null}{aiAnswer ? <div className="ai-answer"><span>Answer</span><p>{aiAnswer}</p></div> : null}</form>
      </section>
    </WorkspaceFrame>
  );
}
