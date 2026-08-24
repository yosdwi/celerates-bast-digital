import { useEffect, useState } from "react";
import { getRuntimeHealth } from "../api/health";
import type { HealthProbe } from "../api/health";
import type { CommandCenterResponse, TalentOpsSession } from "../api/types";
import { RefreshIcon, SyncIcon } from "../components/Icons";
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
  const [loading, setLoading] = useState(false);

  async function refreshHealth() {
    if (loading) return;
    setLoading(true);
    const result = await getRuntimeHealth();
    setLive(result.live);
    setReady(result.ready);
    setLoading(false);
  }

  useEffect(() => { void refreshHealth(); }, []);

  const observedSources = data.sources.filter((source) => source.last_success_at !== null).length;

  return (
    <WorkspaceFrame session={session} active="system" attentionCount={data.summary.need_attention} search={search} onSearch={setSearch} onNavigate={onNavigate} onAskAi={() => onNavigate("/admin/talentops/")}>
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
        </div>

        <section className="panel system-boundary-panel"><div className="panel-title-row"><div><h2>Operational boundaries</h2><span>What this page can and cannot claim</span></div></div><div className="system-boundaries"><div><SyncIcon /><strong>Observed</strong><span>FastAPI liveness/readiness and last successful ingest timestamps.</span></div><div><SyncIcon /><strong>Not inferred</strong><span>Database-specific health, queue depth, Ollama availability, ingest SLA, or source lag thresholds unless exposed by a real backend signal.</span></div></div></section>
      </div>
    </WorkspaceFrame>
  );
}
