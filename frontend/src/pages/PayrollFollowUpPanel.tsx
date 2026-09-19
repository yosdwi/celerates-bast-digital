import { useCallback, useEffect, useState } from "react";
import {
  getPayrollDigest,
  previewPayrollReminder,
  sendManualPayrollReminder,
} from "../api/payroll";
import type {
  PayrollCycle,
  PayrollDigestResponse,
  PayrollFollowUpItem,
  PayrollManualReminderPreview,
} from "../api/payroll";
import type { TalentOpsSession } from "../api/types";

interface Props {
  session: TalentOpsSession;
  cycle: PayrollCycle;
  onRefreshOverview: () => Promise<void>;
}

function reasonLabel(item: PayrollFollowUpItem): string {
  switch (item.reason) {
    case "DELIVERY_UNKNOWN": return "Status kirim tidak pasti — jangan kirim ulang otomatis";
    case "DELIVERY_RETRYABLE_FAILED": return "Pengiriman gagal sementara — retry masih pending";
    case "DELIVERY_FINAL_FAILED": return item.error_code === "whatsapp_identity_not_bound"
      ? "WhatsApp Talent belum terhubung"
      : "Pengiriman gagal dan perlu follow-up";
    case "UNRESPONDED": return "Reminder terkirim, belum ada action attendance";
    case "NOT_REMINDED": return "Belum ada reminder yang berhasil terkirim";
    case "WAITING_REVIEW": return "Sudah diajukan, menunggu review PMO";
    case "SOURCE_UNVERIFIED": return "Data sumber belum terverifikasi";
    default: return item.reason;
  }
}

function stateLabel(item: PayrollFollowUpItem): string {
  if (!item.latest_delivery_state) return "Belum ada delivery";
  const milestone = item.latest_milestone ? ` · ${item.latest_milestone}` : "";
  return `${item.latest_delivery_state}${milestone}`;
}

function blocksManualSend(item: PayrollFollowUpItem): boolean {
  return item.reason === "DELIVERY_UNKNOWN" || item.reason === "DELIVERY_RETRYABLE_FAILED";
}

function outcomeLabel(outcome: string): string {
  switch (outcome) {
    case "sent": return "Reminder berhasil dikirim.";
    case "duplicate": return "Request ini sudah pernah berhasil dikirim.";
    case "unbound": return "WhatsApp Talent belum terhubung.";
    case "not_actionable": return "Attendance sudah berubah dan tidak lagi perlu action Talent.";
    case "not_in_audience": return "Talent tidak termasuk audience Payroll reminder saat ini.";
    case "unknown_blocked": return "Pengiriman sebelumnya UNKNOWN. Kirim ulang diblokir agar tidak duplikat.";
    case "delivery_in_progress": return "Pengiriman lain masih berjalan.";
    case "retry_pending": return "Retry delivery sebelumnya masih pending.";
    case "retryable_failed": return "Bridge WhatsApp belum tersedia. Delivery dicatat untuk retry.";
    case "final_failed": return "Pengiriman gagal final.";
    default: return outcome;
  }
}

export default function PayrollFollowUpPanel({ session, cycle, onRefreshOverview }: Props) {
  const [digest, setDigest] = useState<PayrollDigestResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PayrollManualReminderPreview | null>(null);
  const [previewEmployeeId, setPreviewEmployeeId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const loadDigest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDigest(await getPayrollDigest(cycle.year, cycle.month));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Talent Follow-up tidak dapat dimuat.");
    } finally {
      setLoading(false);
    }
  }, [cycle.month, cycle.year]);

  useEffect(() => {
    setPreview(null);
    setPreviewEmployeeId(null);
    setResult(null);
    void loadDigest();
  }, [loadDigest]);

  async function openPreview(item: PayrollFollowUpItem) {
    setPreviewEmployeeId(item.employee_id);
    setPreview(null);
    setResult(null);
    setError(null);
    try {
      setPreview(await previewPayrollReminder(item.employee_id, cycle.year, cycle.month));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Preview reminder tidak dapat dimuat.");
    }
  }

  async function sendReminder(item: PayrollFollowUpItem) {
    if (blocksManualSend(item)) return;
    setSending(true);
    setResult(null);
    setError(null);
    try {
      const response = await sendManualPayrollReminder(
        session.csrf_token,
        item.employee_id,
        cycle.year,
        cycle.month,
        crypto.randomUUID(),
      );
      setResult(outcomeLabel(response.outcome));
      await Promise.all([loadDigest(), onRefreshOverview()]);
      if (response.sent) setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Reminder tidak dapat dikirim.");
    } finally {
      setSending(false);
    }
  }

  const selectedItem = digest?.items.find((item) => item.employee_id === previewEmployeeId) ?? null;

  return (
    <section className="panel payroll-review-panel" id="payroll-follow-up" aria-label="Payroll Talent Follow-up">
      <div className="panel-title-row payroll-review-heading">
        <div>
          <h2>Talent Follow-up</h2>
          <span>Reminder, response, delivery issue, dan source check dari fakta Payroll terbaru</span>
        </div>
        {digest ? (
          <div className="payroll-review-counts">
            <span><strong>{digest.summary.unresponded_talents}</strong> belum merespons</span>
            <span><strong>{digest.summary.actionable_not_reminded}</strong> belum terkirim</span>
            {digest.summary.delivery_unknown > 0 ? (
              <span className="stale"><strong>{digest.summary.delivery_unknown}</strong> UNKNOWN</span>
            ) : null}
          </div>
        ) : null}
      </div>

      {result ? <div className="payroll-review-result" role="status"><span>{result}</span></div> : null}
      {error ? (
        <div className="payroll-review-error" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => void loadDigest()}>Coba lagi</button>
        </div>
      ) : null}

      {loading && !digest ? (
        <div className="payroll-review-empty" aria-busy="true">Memuat Talent Follow-up…</div>
      ) : digest && digest.items.length === 0 ? (
        <div className="payroll-review-empty">Tidak ada follow-up Payroll yang perlu ditangani.</div>
      ) : digest ? (
        <div className="desktop-table-wrap">
          <table className="data-table" aria-label="Payroll follow-up list">
            <thead>
              <tr>
                <th>Talent</th>
                <th>Perlu perhatian</th>
                <th>Delivery terakhir</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {digest.items.map((item) => (
                <tr key={item.employee_id}>
                  <td>
                    <div className="talent-name">{item.name}</div>
                    <div className="cell-muted">{item.nrp} · {item.role}</div>
                  </td>
                  <td>
                    <strong>{reasonLabel(item)}</strong>
                    <div className="cell-muted">
                      {item.actionable_days > 0 ? `${item.actionable_days} tanggal perlu Talent` : ""}
                      {item.waiting_days > 0 ? `${item.waiting_days} menunggu review` : ""}
                      {item.unverified_days > 0 ? `${item.unverified_days} perlu cek source` : ""}
                    </div>
                  </td>
                  <td>
                    <span className="payroll-status">{stateLabel(item)}</span>
                    {item.error_code ? <div className="cell-muted">{item.error_code}</div> : null}
                  </td>
                  <td>
                    {item.actionable_days > 0 ? (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => void openPreview(item)}
                      >
                        Preview reminder
                      </button>
                    ) : <span className="cell-muted">Tidak perlu kirim reminder</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {previewEmployeeId && selectedItem ? (
        <div className="payroll-review-detail" aria-live="polite">
          <div className="payroll-review-detail-head">
            <div>
              <span>Reminder preview</span>
              <h3>{selectedItem.name}</h3>
              <p>{reasonLabel(selectedItem)}</p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() => {
                setPreviewEmployeeId(null);
                setPreview(null);
              }}
            >
              Tutup
            </button>
          </div>
          {preview ? (
            <>
              {preview.message ? <pre>{preview.message}</pre> : <p>{outcomeLabel(preview.outcome)}</p>}
              {blocksManualSend(selectedItem) ? (
                <div className="payroll-review-warning">
                  Kirim manual diblokir untuk state ini agar tidak membuat delivery duplikat.
                </div>
              ) : (
                <button
                  className="primary-button"
                  type="button"
                  disabled={!preview.eligible || sending}
                  onClick={() => void sendReminder(selectedItem)}
                >
                  {sending ? "Mengirim…" : "Kirim reminder"}
                </button>
              )}
            </>
          ) : <p>Memuat preview…</p>}
        </div>
      ) : null}
    </section>
  );
}
