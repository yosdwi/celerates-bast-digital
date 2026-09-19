import { useCallback, useEffect, useMemo, useState } from "react";
import {
  decidePayrollReviewQueue,
  getPayrollReviewQueue,
} from "../api/payroll";
import type {
  PayrollCycle,
  PayrollReviewDecision,
  PayrollReviewDecisionResponse,
  PayrollReviewItem,
  PayrollReviewQueueResponse,
  PayrollResolutionType,
} from "../api/payroll";
import { attendanceResolutionEvidenceUrl } from "../api/talentops";
import type { TalentOpsSession } from "../api/types";

interface Props {
  session: TalentOpsSession;
  cycle: PayrollCycle;
  onRefreshOverview: () => Promise<void>;
}

const GROUP_ORDER: PayrollResolutionType[] = [
  "missing_clock_out",
  "missing_clock_in",
  "missing_both_worked",
  "absence",
];

const REJECT_REASONS = [
  "Jam tidak sesuai evidence",
  "Evidence tidak cukup jelas",
  "Tanggal atau attendance tidak sesuai",
  "Perlu koreksi informasi dari Talent",
  "Lainnya",
] as const;

function resolutionLabel(value: PayrollResolutionType): string {
  if (value === "missing_clock_in") return "Clock In";
  if (value === "missing_clock_out") return "Clock Out";
  if (value === "missing_both_worked") return "Clock In & Out";
  return "Absence";
}

function reviewabilityLabel(item: PayrollReviewItem): string {
  switch (item.reviewability_reason) {
    case "source_changed": return "Source attendance berubah";
    case "source_unavailable": return "Source belum tersedia";
    case "request_not_current": return "Request bukan state terbaru";
    case "attendance_not_in_projection": return "Attendance tidak ada di projection";
    case "talent_not_in_cycle": return "Talent tidak ada di cycle";
    case "evidence_not_found": return "Evidence tidak ditemukan";
    default: return "Tidak dapat direview";
  }
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Jakarta",
  }).format(new Date(`${value}T00:00:00+07:00`));
}

function submittedLabel(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Jakarta",
  }).format(parsed);
}

function bytesLabel(value: number | null): string {
  if (value === null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function actualLabel(item: PayrollReviewItem): string {
  if (item.resolution_type === "missing_clock_in") return item.raw_check_in ?? "—";
  if (item.resolution_type === "missing_clock_out") return item.raw_check_out ?? "—";
  if (item.resolution_type === "missing_both_worked") {
    return `${item.raw_check_in ?? "—"} → ${item.raw_check_out ?? "—"}`;
  }
  return `${item.raw_check_in ?? "—"} → ${item.raw_check_out ?? "—"}`;
}

function proposedLabel(item: PayrollReviewItem): string {
  if (item.resolution_type === "missing_clock_in") return item.proposed_check_in ?? "—";
  if (item.resolution_type === "missing_clock_out") return item.proposed_check_out ?? "—";
  if (item.resolution_type === "missing_both_worked") {
    return `${item.proposed_check_in ?? "—"} → ${item.proposed_check_out ?? "—"}`;
  }
  return item.absence_type ?? "—";
}

function resultMessage(result: PayrollReviewDecisionResponse): string {
  const parts = [`${result.succeeded} berhasil`];
  if (result.skipped > 0) parts.push(`${result.skipped} dilewati karena state berubah`);
  if (result.failed > 0) parts.push(`${result.failed} gagal`);
  return parts.join(" · ");
}

export default function PayrollReviewQueuePanel({ session, cycle, onRefreshOverview }: Props) {
  const [queue, setQueue] = useState<PayrollReviewQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [decision, setDecision] = useState<PayrollReviewDecision | null>(null);
  const [rejectReason, setRejectReason] = useState<string>(REJECT_REASONS[0]);
  const [otherReason, setOtherReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [decisionResult, setDecisionResult] = useState<PayrollReviewDecisionResponse | null>(null);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getPayrollReviewQueue(cycle.year, cycle.month);
      setQueue(next);
      setSelected((current) => {
        const reviewable = new Set(next.items.filter((item) => item.reviewable).map((item) => item.request_id));
        return new Set([...current].filter((id) => reviewable.has(id)));
      });
      setFocusedId((current) => current && next.items.some((item) => item.request_id === current) ? current : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Review Queue tidak dapat dimuat.");
    } finally {
      setLoading(false);
    }
  }, [cycle.month, cycle.year]);

  useEffect(() => {
    setSelected(new Set());
    setFocusedId(null);
    setDecision(null);
    setDecisionResult(null);
    void loadQueue();
  }, [loadQueue]);

  const groups = useMemo(() => {
    if (!queue) return [];
    return GROUP_ORDER.map((type) => ({
      type,
      items: queue.items.filter((item) => item.resolution_type === type),
    })).filter((group) => group.items.length > 0);
  }, [queue]);

  const focused = queue?.items.find((item) => item.request_id === focusedId) ?? null;
  const selectedCount = selected.size;
  const allReviewable = queue?.items.filter((item) => item.reviewable) ?? [];
  const allSelected = allReviewable.length > 0 && allReviewable.every((item) => selected.has(item.request_id));
  const finalRejectReason = rejectReason === "Lainnya" ? otherReason.trim() : rejectReason;
  const canConfirm = selectedCount > 0
    && !submitting
    && (decision !== "reject" || finalRejectReason.length > 0);

  function toggleSelection(item: PayrollReviewItem) {
    if (!item.reviewable) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(item.request_id)) next.delete(item.request_id);
      else next.add(item.request_id);
      return next;
    });
  }

  function toggleAllReviewable() {
    setSelected(allSelected ? new Set() : new Set(allReviewable.map((item) => item.request_id)));
  }

  async function confirmDecision() {
    if (!decision || !canConfirm) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await decidePayrollReviewQueue(
        session.csrf_token,
        cycle.year,
        cycle.month,
        [...selected],
        decision,
        decision === "reject" ? finalRejectReason : undefined,
      );
      setDecisionResult(result);
      setSelected(new Set());
      setDecision(null);
      await Promise.all([loadQueue(), onRefreshOverview()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Keputusan review tidak dapat disimpan.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel payroll-review-panel" id="payroll-review-queue" aria-label="Payroll Review Queue">
      <div className="panel-title-row payroll-review-heading">
        <div>
          <h2>Review Queue</h2>
          <span>Pengajuan Talent yang menunggu keputusan PMO</span>
        </div>
        {queue ? (
          <div className="payroll-review-counts">
            <span><strong>{queue.summary.reviewable}</strong> siap review</span>
            {queue.summary.stale > 0 ? <span className="stale"><strong>{queue.summary.stale}</strong> berubah</span> : null}
          </div>
        ) : null}
      </div>

      {decisionResult ? (
        <div className="payroll-review-result" role="status">
          <strong>Review selesai.</strong>
          <span>{resultMessage(decisionResult)}</span>
        </div>
      ) : null}

      {error ? (
        <div className="payroll-review-error" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadQueue()}>Coba lagi</button>
        </div>
      ) : null}

      {loading && !queue ? (
        <div className="payroll-review-empty" aria-busy="true">Memuat Review Queue…</div>
      ) : queue && queue.items.length === 0 ? (
        <div className="payroll-review-empty">Tidak ada pengajuan attendance yang menunggu review di cycle ini.</div>
      ) : queue ? (
        <>
          <div className="payroll-review-toolbar">
            <button className="secondary-button" type="button" onClick={toggleAllReviewable} disabled={allReviewable.length === 0}>
              {allSelected ? "Batalkan pilihan" : "Pilih semua siap review"}
            </button>
            <span>{selectedCount} dipilih</span>
            <div className="payroll-review-actions">
              <button className="secondary-button" type="button" disabled={selectedCount === 0 || submitting} onClick={() => setDecision("reject")}>Tolak</button>
              <button className="primary-button" type="button" disabled={selectedCount === 0 || submitting} onClick={() => setDecision("approve")}>Setujui</button>
            </div>
          </div>

          <div className="payroll-review-layout">
            <div className="payroll-review-groups">
              {groups.map((group) => (
                <div className="payroll-review-group" key={group.type}>
                  <div className="payroll-review-group-title">
                    <strong>{resolutionLabel(group.type)}</strong>
                    <span>{group.items.length}</span>
                  </div>
                  {group.items.map((item) => (
                    <div className={`payroll-review-row${item.reviewable ? "" : " stale"}`} key={item.request_id}>
                      <label className="payroll-review-check">
                        <input
                          type="checkbox"
                          checked={selected.has(item.request_id)}
                          disabled={!item.reviewable}
                          onChange={() => toggleSelection(item)}
                          aria-label={`Pilih pengajuan ${item.name} ${dateLabel(item.work_date)}`}
                        />
                      </label>
                      <button className="payroll-review-open" type="button" onClick={() => setFocusedId(item.request_id)}>
                        <span className="payroll-review-person">
                          <strong>{item.name}</strong>
                          <small>{item.nrp} · {dateLabel(item.work_date)}</small>
                        </span>
                        <span className="payroll-review-change">
                          <small>Aktual → usulan</small>
                          <strong>{actualLabel(item)} → {proposedLabel(item)}</strong>
                        </span>
                        <span className={item.reviewable ? "payroll-review-ready" : "payroll-review-stale"}>
                          {item.reviewable ? "Siap review" : reviewabilityLabel(item)}
                        </span>
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            {focused ? (
              <aside className="payroll-review-detail" aria-label={`Detail review ${focused.name}`}>
                <div className="payroll-review-detail-head">
                  <div>
                    <span>Review detail</span>
                    <h3>{focused.name}</h3>
                    <p>{focused.nrp} · {focused.role} · {dateLabel(focused.work_date)}</p>
                  </div>
                  <button type="button" className="secondary-button" onClick={() => setFocusedId(null)}>Tutup</button>
                </div>
                {!focused.reviewable ? (
                  <div className="payroll-review-warning">
                    <strong>Tidak dapat diputuskan dari state sekarang.</strong>
                    <span>{reviewabilityLabel(focused)}</span>
                  </div>
                ) : null}
                <dl className="payroll-review-facts">
                  <div><dt>Jenis</dt><dd>{resolutionLabel(focused.resolution_type)}</dd></div>
                  <div><dt>Clock In aktual</dt><dd>{focused.raw_check_in ?? "—"}</dd></div>
                  <div><dt>Clock Out aktual</dt><dd>{focused.raw_check_out ?? "—"}</dd></div>
                  <div><dt>Clock In usulan</dt><dd>{focused.proposed_check_in ?? "—"}</dd></div>
                  <div><dt>Clock Out usulan</dt><dd>{focused.proposed_check_out ?? "—"}</dd></div>
                  <div><dt>Absence</dt><dd>{focused.absence_type ?? "—"}</dd></div>
                  <div><dt>Diajukan</dt><dd>{submittedLabel(focused.submitted_at)}</dd></div>
                  <div><dt>Evidence</dt><dd>{focused.evidence_content_type ?? "unknown"} · {bytesLabel(focused.evidence_byte_size)}</dd></div>
                </dl>
                {focused.evidence_caption ? <p className="payroll-review-caption">“{focused.evidence_caption}”</p> : null}
                {focused.evidence_content_type ? (
                  <a
                    className="secondary-button payroll-review-evidence-link"
                    href={attendanceResolutionEvidenceUrl(focused.request_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Buka evidence
                  </a>
                ) : null}
              </aside>
            ) : (
              <aside className="payroll-review-detail empty">Pilih row untuk melihat actual, proposed, dan evidence metadata.</aside>
            )}
          </div>

          {decision ? (
            <div className="payroll-review-confirm" role="dialog" aria-label="Konfirmasi keputusan Payroll">
              <div>
                <strong>{decision === "approve" ? `Setujui ${selectedCount} pengajuan?` : `Tolak ${selectedCount} pengajuan?`}</strong>
                <span>Setiap item akan divalidasi ulang. Item yang berubah akan dilewati tanpa menggagalkan item lain.</span>
              </div>
              {decision === "reject" ? (
                <div className="payroll-review-reject-form">
                  <label>
                    Alasan
                    <select value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}>
                      {REJECT_REASONS.map((reason) => <option key={reason} value={reason}>{reason}</option>)}
                    </select>
                  </label>
                  {rejectReason === "Lainnya" ? (
                    <label>
                      Detail alasan
                      <textarea value={otherReason} maxLength={500} onChange={(event) => setOtherReason(event.target.value)} placeholder="Tulis alasan yang akan dilihat pada histori review" />
                    </label>
                  ) : null}
                </div>
              ) : null}
              <div className="payroll-review-confirm-actions">
                <button className="secondary-button" type="button" disabled={submitting} onClick={() => setDecision(null)}>Batal</button>
                <button className={decision === "approve" ? "primary-button" : "danger-button"} type="button" disabled={!canConfirm} onClick={() => void confirmDecision()}>
                  {submitting ? "Memproses…" : decision === "approve" ? "Ya, setujui" : "Ya, tolak"}
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
