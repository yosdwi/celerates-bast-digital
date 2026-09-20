import { useEffect, useState } from "react";
import type { PayrollCycle } from "../api/payroll";
import {
  exportPayrollAttendance,
  getPayrollExportHistory,
} from "../api/payrollExport";
import type {
  PayrollExportHistoryItem,
  PayrollExportReportType,
} from "../api/payrollExport";
import type { TalentOpsSession } from "../api/types";
import "../styles/payroll-export.css";

interface Props {
  session: TalentOpsSession;
  cycle: PayrollCycle;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
] as const;

function formatDate(value: string): string {
  const [yearText, monthText, dayText] = value.split("-");
  const month = Number(monthText);
  const day = Number(dayText);
  const monthLabel = MONTHS[month - 1];
  if (!yearText || !monthLabel || !Number.isFinite(day)) return value;
  return `${day} ${monthLabel} ${yearText}`;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Jakarta",
  }).format(parsed);
}

function reportLabel(item: PayrollExportHistoryItem): string {
  return item.report_type === "developer" ? "Developer" : "IoT Operations";
}

function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export default function PayrollExportPanel({ session, cycle }: Props) {
  const [reportType, setReportType] = useState<PayrollExportReportType>("developer");
  const [history, setHistory] = useState<PayrollExportHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<string | null>(null);

  async function refreshHistory(): Promise<void> {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await getPayrollExportHistory(cycle.year, cycle.month);
      setHistory(result.items);
    } catch (reason) {
      setHistoryError(
        reason instanceof Error ? reason.message : "Riwayat export tidak dapat dimuat.",
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    setConfirming(false);
    setExportError(null);
    setExportResult(null);
    setHistoryLoading(true);
    setHistoryError(null);
    void getPayrollExportHistory(cycle.year, cycle.month)
      .then((result) => {
        if (active) setHistory(result.items);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setHistoryError(
          reason instanceof Error ? reason.message : "Riwayat export tidak dapat dimuat.",
        );
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [cycle.cycle_id, cycle.month, cycle.year]);

  async function runExport(): Promise<void> {
    setExporting(true);
    setExportError(null);
    setExportResult(null);
    try {
      const result = await exportPayrollAttendance(
        session.csrf_token,
        cycle.year,
        cycle.month,
        reportType,
      );
      downloadBlob(result.blob, result.filename);
      setExportResult(
        `${result.filename}${result.rowCount === null ? "" : ` · ${result.rowCount} baris`}`,
      );
      setConfirming(false);
      await refreshHistory();
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "Export Payroll gagal.");
    } finally {
      setExporting(false);
    }
  }

  const selectedRole = reportType === "developer" ? "Developer" : "IoT Operations";
  const cycleRange = `${formatDate(cycle.start)} – ${formatDate(cycle.end)}`;

  return (
    <section className="panel payroll-export-panel" aria-label="Export Payroll attendance">
      <div className="payroll-export-heading">
        <div>
          <span className="payroll-card-kicker">Payroll Export</span>
          <h2>Attendance CSV</h2>
          <p>
            {cycle.label} · {cycleRange}. File memakai attendance correction projection terbaru
            melalui exporter CSV existing.
          </p>
        </div>
        <div className="payroll-export-controls">
          <label>
            <span>Role</span>
            <select
              value={reportType}
              onChange={(event) => {
                setReportType(event.target.value as PayrollExportReportType);
                setConfirming(false);
                setExportError(null);
                setExportResult(null);
              }}
              disabled={exporting}
            >
              <option value="developer">Developer</option>
              <option value="shifting">IoT Operations</option>
            </select>
          </label>
          <button
            className="secondary-button"
            type="button"
            disabled={exporting}
            onClick={() => setConfirming(true)}
          >
            Export CSV
          </button>
        </div>
      </div>

      {confirming ? (
        <div className="payroll-export-confirm" role="status">
          <div>
            <strong>Konfirmasi export {selectedRole}</strong>
            <span>{cycle.label} · {cycleRange}</span>
            <small>Export hanya membaca data authoritative saat ini; tidak mengubah attendance.</small>
          </div>
          <div>
            <button
              className="secondary-button"
              type="button"
              disabled={exporting}
              onClick={() => setConfirming(false)}
            >
              Batal
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={exporting}
              onClick={() => void runExport()}
            >
              {exporting ? "Menyiapkan…" : "Ya, export CSV"}
            </button>
          </div>
        </div>
      ) : null}

      {exportError ? <div className="payroll-export-message error">{exportError}</div> : null}
      {exportResult ? (
        <div className="payroll-export-message success" role="status">Export selesai · {exportResult}</div>
      ) : null}

      <div className="payroll-export-history-heading">
        <div>
          <strong>Riwayat export</strong>
          <span>Metadata saja; file CSV tidak diduplikasi ke history.</span>
        </div>
        <button
          className="secondary-button"
          type="button"
          disabled={historyLoading || exporting}
          onClick={() => void refreshHistory()}
        >
          Refresh
        </button>
      </div>

      {historyLoading ? (
        <div className="payroll-export-empty" aria-busy="true">Memuat riwayat export…</div>
      ) : historyError ? (
        <div className="payroll-export-empty error">{historyError}</div>
      ) : history.length === 0 ? (
        <div className="payroll-export-empty">Belum ada export untuk cycle ini.</div>
      ) : (
        <div className="payroll-export-history-list">
          {history.map((item) => (
            <article key={item.export_id}>
              <div>
                <strong>{item.filename}</strong>
                <span>{reportLabel(item)} · {item.row_count} baris</span>
              </div>
              <div>
                <span>{formatTimestamp(item.exported_at)}</span>
                <small>{item.exported_by}</small>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
