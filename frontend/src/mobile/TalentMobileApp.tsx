import { useCallback, useEffect, useMemo, useState } from "react";
import {
  captureTalentToken,
  getTalentMobileOverview,
  submitTalentAttendance,
  uploadTalentTaskEvidence,
} from "../api/talentMobile";
import type {
  AttendanceResolutionInput,
  TalentMobileAttendanceItem,
  TalentMobileOverview,
  TalentMobileTab,
} from "../api/talentMobile";

type TaskFilter = "missing" | "complete";
type AttendanceAction = AttendanceResolutionInput["action"];

interface AttendanceDraft {
  action: AttendanceAction;
  checkIn: string;
  checkOut: string;
  file: File | null;
}

function initialTab(): TalentMobileTab {
  return new URLSearchParams(window.location.search).get("tab") === "tasks" ? "tasks" : "attendance";
}

function dateLabel(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "long" }).format(
    new Date(year, month - 1, day),
  );
}

function gapLabel(item: TalentMobileAttendanceItem): string {
  if (item.gap === "missing_clock_in") return "Clock In belum terisi";
  if (item.gap === "missing_clock_out") return "Clock Out belum terisi";
  return "Clock In & Clock Out belum terisi";
}

function Loading() {
  return (
    <main className="talent-mobile-state" aria-busy="true">
      <div className="talent-mobile-spinner" />
      <p>Menyiapkan data kamu…</p>
    </main>
  );
}

function FatalState({ message }: { message: string }) {
  return (
    <main className="talent-mobile-state">
      <div className="talent-mobile-state-icon">!</div>
      <h1>Link tidak bisa dibuka</h1>
      <p>{message}</p>
      <small>Kembali ke WhatsApp lalu minta link baru dari Digital BAST.</small>
    </main>
  );
}

export default function TalentMobileApp() {
  const [data, setData] = useState<TalentMobileOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TalentMobileTab>(initialTab);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("missing");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, AttendanceDraft>>({});

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setData(await getTalentMobileOverview());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Data tidak dapat dimuat.");
    }
  }, []);

  useEffect(() => {
    const token = captureTalentToken();
    if (!token) {
      setError("Link tidak tersedia atau sudah dibuka di sesi browser lain.");
      setLoading(false);
      return;
    }
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  const visibleTasks = useMemo(() => {
    if (!data) return [];
    return data.task.items.filter((item) => (taskFilter === "complete" ? item.complete : !item.complete));
  }, [data, taskFilter]);

  function switchTab(next: TalentMobileTab) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setNotice(null);
  }

  async function uploadTask(taskKey: string, file: File | null) {
    if (!file || busyKey) return;
    setBusyKey(`task:${taskKey}`);
    setNotice(null);
    try {
      const result = await uploadTalentTaskEvidence(taskKey, file);
      setNotice(result.message);
      await refresh();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Evidence gagal disimpan.");
    } finally {
      setBusyKey(null);
    }
  }

  function draftFor(item: TalentMobileAttendanceItem): AttendanceDraft {
    return drafts[item.attendance_key] ?? {
      action: "worked",
      checkIn: "",
      checkOut: "",
      file: null,
    };
  }

  function patchDraft(item: TalentMobileAttendanceItem, patch: Partial<AttendanceDraft>) {
    setDrafts((current) => ({
      ...current,
      [item.attendance_key]: { ...draftFor(item), ...current[item.attendance_key], ...patch },
    }));
  }

  async function submitAttendance(item: TalentMobileAttendanceItem) {
    if (busyKey) return;
    const draft = draftFor(item);
    if (!draft.file) {
      setNotice("Tambahkan foto evidence dulu sebelum mengajukan.");
      return;
    }
    setBusyKey(`attendance:${item.attendance_key}`);
    setNotice(null);
    try {
      const result = await submitTalentAttendance(item.attendance_key, {
        action: draft.action,
        checkIn: draft.checkIn || undefined,
        checkOut: draft.checkOut || undefined,
        file: draft.file,
      });
      setNotice(result.message);
      setDrafts((current) => {
        const next = { ...current };
        delete next[item.attendance_key];
        return next;
      });
      await refresh();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Pengajuan attendance gagal.");
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) return <Loading />;
  if (error || !data) return <FatalState message={error ?? "Data belum tersedia."} />;

  return (
    <div className="talent-mobile-shell">
      <header className="talent-mobile-header">
        <div>
          <span className="talent-mobile-eyebrow">DIGITAL BAST</span>
          <h1>{data.name}</h1>
          <p>{data.period.label}</p>
        </div>
        <div className="talent-mobile-header-mark">C</div>
      </header>

      <section className="talent-mobile-summary" aria-label="Ringkasan">
        <button type="button" className={tab === "attendance" ? "active" : ""} onClick={() => switchTab("attendance")}>
          <span>Attendance</span>
          <strong>{data.attendance.needs_action}</strong>
          <small>perlu tindakan</small>
        </button>
        <button type="button" className={tab === "tasks" ? "active" : ""} onClick={() => switchTab("tasks")}>
          <span>Task Evidence</span>
          <strong>{data.task.complete}/{data.task.closed}</strong>
          <small>{data.task.missing} belum lengkap</small>
        </button>
      </section>

      {notice ? <div className="talent-mobile-notice" role="status">{notice}</div> : null}

      {tab === "tasks" ? (
        <main className="talent-mobile-content">
          <div className="talent-mobile-section-head">
            <div>
              <h2>Task Evidence</h2>
              <p>Upload langsung di task yang sesuai. Tidak perlu pilih nomor di WhatsApp.</p>
            </div>
            <div className="talent-mobile-progress" aria-label={`${data.task.complete} dari ${data.task.closed} lengkap`}>
              <span style={{ width: `${data.task.closed ? (data.task.complete / data.task.closed) * 100 : 100}%` }} />
            </div>
          </div>

          <div className="talent-mobile-chips">
            <button type="button" className={taskFilter === "missing" ? "active" : ""} onClick={() => setTaskFilter("missing")}>
              Belum lengkap <b>{data.task.missing}</b>
            </button>
            <button type="button" className={taskFilter === "complete" ? "active" : ""} onClick={() => setTaskFilter("complete")}>
              Lengkap <b>{data.task.complete}</b>
            </button>
          </div>

          <div className="talent-mobile-card-list">
            {visibleTasks.length ? visibleTasks.map((item) => (
              <article className={`talent-mobile-card task ${item.complete ? "complete" : ""}`} key={`${item.task_source}:${item.task_key}`}>
                <div className="talent-mobile-card-topline">
                  <span>{dateLabel(item.work_date)}</span>
                  <span className={item.complete ? "status-ok" : "status-needed"}>{item.complete ? "✓ Lengkap" : "Belum ada evidence"}</span>
                </div>
                <h3>{item.title}</h3>
                <p className="talent-mobile-source">Closed · {item.task_source}</p>
                {item.complete ? (
                  <div className="talent-mobile-complete-row">✓ Evidence sudah tersimpan</div>
                ) : (
                  <label className={`talent-mobile-upload ${busyKey === `task:${item.task_key}` ? "busy" : ""}`}>
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      disabled={busyKey !== null}
                      onChange={(event) => void uploadTask(item.task_key, event.target.files?.[0] ?? null)}
                    />
                    <span>{busyKey === `task:${item.task_key}` ? "Mengupload…" : "+ Tambah Evidence"}</span>
                    <small>Foto dari kamera atau galeri · maks. 5 MB</small>
                  </label>
                )}
              </article>
            )) : (
              <div className="talent-mobile-empty">{taskFilter === "missing" ? "Semua closed task sudah punya evidence ✓" : "Belum ada task yang lengkap."}</div>
            )}
          </div>
        </main>
      ) : (
        <main className="talent-mobile-content">
          <div className="talent-mobile-section-head">
            <div>
              <h2>Attendance</h2>
              <p>Lengkapi gap dan evidence dalam satu card, lalu kirim ke PMO.</p>
            </div>
          </div>

          {data.attendance.requests.filter((item) => item.status === "pending").length ? (
            <section className="talent-mobile-request-strip">
              <strong>Menunggu PMO</strong>
              {data.attendance.requests.filter((item) => item.status === "pending").map((item) => (
                <span key={item.id}>{dateLabel(item.work_date)} · {item.label}</span>
              ))}
            </section>
          ) : null}

          {data.attendance.missing_data_days.length ? (
            <section className="talent-mobile-data-warning">
              <strong>Data belum masuk sistem</strong>
              <p>{data.attendance.missing_data_days.map(dateLabel).join(", ")}. Ini bukan masalah evidence; admin perlu cek sinkronisasi data.</p>
            </section>
          ) : null}

          <div className="talent-mobile-card-list">
            {data.attendance.items.length ? data.attendance.items.map((item) => {
              const draft = draftFor(item);
              const bothMissing = item.gap === "missing_both";
              const busy = busyKey === `attendance:${item.attendance_key}`;
              return (
                <article className="talent-mobile-card attendance" key={item.attendance_key}>
                  <div className="talent-mobile-card-topline">
                    <span>{dateLabel(item.work_date)}</span>
                    <span className="status-needed">Perlu tindakan</span>
                  </div>
                  <h3>{gapLabel(item)}</h3>
                  <div className="talent-mobile-clock-row">
                    <div><small>Clock In</small><strong>{item.check_in ?? "—"}</strong></div>
                    <div><small>Clock Out</small><strong>{item.check_out ?? "—"}</strong></div>
                  </div>

                  {bothMissing ? (
                    <div className="talent-mobile-action-group">
                      <span>Apa yang terjadi?</span>
                      <div>
                        {(["worked", "sakit", "izin", "cuti"] as AttendanceAction[]).map((action) => (
                          <button
                            type="button"
                            className={draft.action === action ? "active" : ""}
                            key={action}
                            onClick={() => patchDraft(item, { action })}
                          >
                            {action === "worked" ? "Saya bekerja" : action.charAt(0).toUpperCase() + action.slice(1)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {draft.action === "worked" ? (
                    <div className="talent-mobile-time-grid">
                      {(item.gap === "missing_clock_in" || bothMissing) ? (
                        <label>Jam masuk<input type="time" value={draft.checkIn} onChange={(event) => patchDraft(item, { checkIn: event.target.value })} /></label>
                      ) : null}
                      {(item.gap === "missing_clock_out" || bothMissing) ? (
                        <label>Jam pulang<input type="time" value={draft.checkOut} onChange={(event) => patchDraft(item, { checkOut: event.target.value })} /></label>
                      ) : null}
                    </div>
                  ) : null}

                  <label className="talent-mobile-file-row">
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      disabled={busyKey !== null}
                      onChange={(event) => patchDraft(item, { file: event.target.files?.[0] ?? null })}
                    />
                    <span>{draft.file ? draft.file.name : "+ Tambah Foto Evidence"}</span>
                  </label>

                  <button className="talent-mobile-submit" type="button" disabled={busyKey !== null || !draft.file} onClick={() => void submitAttendance(item)}>
                    {busy ? "Mengirim…" : "Ajukan ke PMO"}
                  </button>
                  <small className="talent-mobile-rule-note">Raw attendance tetap tidak diubah.</small>
                </article>
              );
            }) : (
              <div className="talent-mobile-empty">Tidak ada attendance yang perlu dilengkapi saat ini ✓</div>
            )}
          </div>
        </main>
      )}
    </div>
  );
}
