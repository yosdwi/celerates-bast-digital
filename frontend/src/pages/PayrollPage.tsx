import { useMemo, useState } from "react";
import type { PayrollOverviewResponse, PayrollTalentRow } from "../api/payroll";
import type { TalentOpsSession } from "../api/types";
import WorkspaceFrame from "../components/WorkspaceFrame";

type PayrollFilter = "all" | "needs" | "waiting" | "complete" | "unverified";

interface Props {
  session: TalentOpsSession;
  data: PayrollOverviewResponse;
  onNavigate: (path: string) => void;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
] as const;

function formatDate(value: string): string {
  const [yearText, monthText, dayText] = value.split("-");
  const month = Number(monthText);
  const day = Number(dayText);
  if (!yearText || !Number.isFinite(month) || !Number.isFinite(day) || !MONTHS[month - 1]) {
    return value;
  }
  return `${day} ${MONTHS[month - 1]} ${yearText}`;
}

function cycleRange(start: string, end: string): string {
  const [startYear, startMonth, startDay] = start.split("-");
  const [endYear, endMonth, endDay] = end.split("-");
  const startLabel = `${Number(startDay)} ${MONTHS[Number(startMonth) - 1] ?? startMonth}`;
  const endLabel = `${Number(endDay)} ${MONTHS[Number(endMonth) - 1] ?? endMonth}`;
  return startYear === endYear
    ? `${startLabel} – ${endLabel} ${endYear}`
    : `${startLabel} ${startYear} – ${endLabel} ${endYear}`;
}

function aggregateLabel(talent: PayrollTalentRow): string {
  if (talent.actionable_days > 0) return "Perlu Talent";
  if (talent.unverified_days > 0) return "Perlu cek data";
  if (talent.waiting_days > 0) return "Menunggu review";
  return "Complete";
}

function aggregateClass(talent: PayrollTalentRow): string {
  if (talent.actionable_days > 0) return "needs";
  if (talent.unverified_days > 0) return "unverified";
  if (talent.waiting_days > 0) return "waiting";
  return "complete";
}

function filterMatches(talent: PayrollTalentRow, filter: PayrollFilter): boolean {
  if (filter === "needs") return talent.actionable_days > 0;
  if (filter === "unverified") return talent.unverified_days > 0;
  if (filter === "waiting") return talent.waiting_days > 0;
  if (filter === "complete") {
    return talent.actionable_days === 0
      && talent.waiting_days === 0
      && talent.unverified_days === 0;
  }
  return true;
}

function dayMeta(talent: PayrollTalentRow): string {
  const parts: string[] = [];
  if (talent.actionable_days > 0) parts.push(`${talent.actionable_days} perlu dilengkapi`);
  if (talent.waiting_days > 0) parts.push(`${talent.waiting_days} menunggu review`);
  if (talent.unverified_days > 0) parts.push(`${talent.unverified_days} belum terverifikasi`);
  if (parts.length === 0) parts.push(`${talent.complete_days} hari complete`);
  return parts.join(" · ");
}

export default function PayrollPage({ session, data, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<PayrollFilter>("all");

  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return data.talents.filter((talent) => {
      const searchOk = !needle
        || `${talent.name} ${talent.nrp} ${talent.role}`.toLocaleLowerCase().includes(needle);
      return searchOk && filterMatches(talent, filter);
    });
  }, [data.talents, filter, search]);

  const waitingTalents = data.talents.filter((talent) => talent.waiting_days > 0).length;
  const waitingDays = data.talents.reduce((total, talent) => total + talent.waiting_days, 0);
  const actionTalents = data.talents.filter((talent) => talent.actionable_days > 0).length;
  const actionDays = data.talents.reduce((total, talent) => total + talent.actionable_days, 0);
  const unverifiedDays = data.talents.reduce((total, talent) => total + talent.unverified_days, 0);

  return (
    <WorkspaceFrame
      session={session}
      active="payroll"
      attentionCount={actionTalents}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => undefined}
      showAi={false}
    >
      <div className="content payroll-content">
        <div className="page-heading payroll-heading">
          <div>
            <h1>Payroll</h1>
            <p>
              {data.cycle.label} · {cycleRange(data.cycle.start, data.cycle.end)}
              {data.evaluated_through
                ? ` · Dievaluasi s.d. ${formatDate(data.evaluated_through)}`
                : " · Belum ada hari yang siap dievaluasi"}
            </p>
          </div>
          <div className="payroll-total" aria-label="Total Talent">
            <span>Total Talent</span>
            <strong>{data.summary.total_talents}</strong>
          </div>
        </div>

        <section className="payroll-summary" aria-label="Ringkasan Payroll">
          <button type="button" onClick={() => setFilter("complete")}>
            <span className="payroll-summary-label">Complete</span>
            <strong>{data.summary.complete}</strong>
            <small>Tidak ada action attendance</small>
          </button>
          <button type="button" onClick={() => setFilter("needs")}>
            <span className="payroll-summary-label">Perlu Talent</span>
            <strong>{data.summary.needs_talent_action}</strong>
            <small>{actionDays} tanggal perlu dilengkapi</small>
          </button>
          <button type="button" onClick={() => setFilter("waiting")}>
            <span className="payroll-summary-label">Menunggu review</span>
            <strong>{data.summary.waiting_submitted}</strong>
            <small>{waitingDays} pengajuan menunggu PMO</small>
          </button>
        </section>

        {data.summary.unverified > 0 ? (
          <div className="payroll-source-notice" role="status">
            <strong>{data.summary.unverified} Talent perlu cek data sumber.</strong>
            <span>{unverifiedDays} tanggal belum terverifikasi dan tidak akan dianggap action Talent.</span>
            <button type="button" onClick={() => setFilter("unverified")}>Lihat</button>
          </div>
        ) : null}

        <div className="payroll-work-grid">
          <section className="panel payroll-work-card" aria-label="Review Queue">
            <div>
              <span className="payroll-card-kicker">Review Queue</span>
              <strong>{waitingDays}</strong>
              <p>{waitingTalents} Talent punya pengajuan yang menunggu review.</p>
            </div>
            <button className="secondary-button" type="button" onClick={() => setFilter("waiting")}>
              Lihat daftar
            </button>
          </section>

          <section className="panel payroll-work-card" aria-label="Talent Follow-up">
            <div>
              <span className="payroll-card-kicker">Talent Follow-up</span>
              <strong>{actionDays}</strong>
              <p>{actionTalents} Talent masih perlu melengkapi attendance.</p>
            </div>
            <button className="secondary-button" type="button" onClick={() => setFilter("needs")}>
              Lihat daftar
            </button>
          </section>
        </div>

        <section className="panel payroll-talent-panel">
          <div className="panel-title-row payroll-list-heading">
            <div>
              <h2>Status Talent</h2>
              <span>{visible.length} dari {data.talents.length} Talent</span>
            </div>
          </div>

          <div className="filter-chips payroll-filter-chips" role="group" aria-label="Filter status Payroll">
            <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>Semua</button>
            <button type="button" className={filter === "needs" ? "active" : ""} onClick={() => setFilter("needs")}>Perlu Talent</button>
            <button type="button" className={filter === "waiting" ? "active" : ""} onClick={() => setFilter("waiting")}>Menunggu review</button>
            <button type="button" className={filter === "complete" ? "active" : ""} onClick={() => setFilter("complete")}>Complete</button>
            {data.summary.unverified > 0 ? (
              <button type="button" className={filter === "unverified" ? "active" : ""} onClick={() => setFilter("unverified")}>Perlu cek data</button>
            ) : null}
          </div>

          {visible.length === 0 ? (
            <div className="empty-state">Tidak ada Talent yang cocok dengan filter saat ini.</div>
          ) : (
            <>
              <div className="desktop-table-wrap payroll-desktop-list">
                <table className="data-table payroll-table" aria-label="Payroll talent list">
                  <thead>
                    <tr>
                      <th>Talent</th>
                      <th>Status</th>
                      <th>Dievaluasi</th>
                      <th>Complete</th>
                      <th>Menunggu</th>
                      <th>Perlu Talent</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((talent) => (
                      <tr key={talent.employee_id}>
                        <td>
                          <div className="talent-name">{talent.name}</div>
                          <div className="cell-muted">{talent.nrp} · {talent.role}</div>
                        </td>
                        <td><span className={`payroll-status ${aggregateClass(talent)}`}>{aggregateLabel(talent)}</span></td>
                        <td>{talent.evaluated_days}</td>
                        <td>{talent.complete_days}</td>
                        <td>{talent.waiting_days}</td>
                        <td>{talent.actionable_days}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="payroll-mobile-list" aria-label="Payroll talent mobile list">
                {visible.map((talent) => (
                  <article className="payroll-mobile-row" key={talent.employee_id}>
                    <div className="payroll-mobile-head">
                      <div>
                        <strong>{talent.name}</strong>
                        <span>{talent.nrp} · {talent.role}</span>
                      </div>
                      <span className={`payroll-status ${aggregateClass(talent)}`}>{aggregateLabel(talent)}</span>
                    </div>
                    <p>{dayMeta(talent)}</p>
                    <div className="payroll-mobile-metrics">
                      <span><small>Dievaluasi</small><strong>{talent.evaluated_days}</strong></span>
                      <span><small>Complete</small><strong>{talent.complete_days}</strong></span>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </WorkspaceFrame>
  );
}
