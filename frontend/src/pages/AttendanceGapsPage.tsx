import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { getAttendanceGaps, submitAttendanceGap } from "../api/talentops";
import type { AttendanceGapItem, CommandCenterResponse, TalentOpsSession } from "../api/types";
import { SearchIcon } from "../components/Icons";
import WorkspaceFrame from "../components/WorkspaceFrame";

type GapAction = "worked" | "sakit" | "izin" | "cuti" | "libur";
type GroupBy = "talent" | "date";

interface Draft {
  action: GapAction;
  checkIn: string;
  checkOut: string;
  file: File | null;
}

interface Props {
  session: TalentOpsSession;
  data: CommandCenterResponse;
  onNavigate: (path: string) => void;
}

interface Group {
  key: string;
  label: string;
  items: AttendanceGapItem[];
}

function dateLabel(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "long" }).format(new Date(year, month - 1, day));
}

function gapLabel(item: AttendanceGapItem): string {
  if (item.gap === "missing_clock_in") return "Clock In kosong";
  if (item.gap === "missing_clock_out") return "Clock Out kosong";
  return "Clock In & Clock Out kosong";
}

function groupItems(items: AttendanceGapItem[], groupBy: GroupBy): Group[] {
  const map = new Map<string, Group>();
  for (const item of items) {
    const key = groupBy === "talent" ? item.employee_id : item.work_date;
    const label = groupBy === "talent" ? item.name : dateLabel(item.work_date);
    const group = map.get(key);
    if (group) group.items.push(item);
    else map.set(key, { key, label, items: [item] });
  }
  const groups = Array.from(map.values());
  groups.sort((a, b) => (groupBy === "talent" ? a.label.localeCompare(b.label, "id") : a.key.localeCompare(b.key)));
  for (const group of groups) {
    group.items.sort((a, b) =>
      groupBy === "talent" ? a.work_date.localeCompare(b.work_date) : a.name.localeCompare(b.name, "id"),
    );
  }
  return groups;
}

const EMPTY_DRAFT: Draft = { action: "worked", checkIn: "", checkOut: "", file: null };

export default function AttendanceGapsPage({ session, data, onNavigate }: Props) {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<AttendanceGapItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("talent");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  function toggleGroup(key: string) {
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const period = { year: data.period.year, month: data.period.month };

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const response = await getAttendanceGaps(period.year, period.month);
      setItems(response.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Attendance gap tidak dapat dimuat.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.year, period.month]);

  useEffect(() => {
    setLoading(true);
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const visible = useMemo(
    () => (items ?? []).filter((item) => !normalizedSearch || item.name.toLocaleLowerCase().includes(normalizedSearch)),
    [items, normalizedSearch],
  );
  const groups = useMemo(() => groupItems(visible, groupBy), [visible, groupBy]);

  function draftFor(item: AttendanceGapItem): Draft {
    return drafts[item.attendance_key] ?? EMPTY_DRAFT;
  }

  function patchDraft(item: AttendanceGapItem, patch: Partial<Draft>) {
    setDrafts((current) => ({ ...current, [item.attendance_key]: { ...draftFor(item), ...patch } }));
  }

  async function submit(item: AttendanceGapItem) {
    if (busyKey) return;
    const draft = draftFor(item);
    if (!draft.file) {
      setNotice("Tambahkan foto evidence dulu sebelum menyimpan.");
      return;
    }
    setBusyKey(item.attendance_key);
    setNotice(null);
    try {
      const result = await submitAttendanceGap(session.csrf_token, item.employee_id, item.attendance_key, period, {
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
      setOpenKey(null);
      await refresh();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Pengajuan attendance gagal.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <WorkspaceFrame
      session={session}
      active="actions"
      attentionCount={data.summary.need_attention}
      search={search}
      onSearch={setSearch}
      onNavigate={onNavigate}
      onAskAi={() => {}}
    >
      <div className="content action-center-page">
        <div className="page-heading">
          <div>
            <h1>Attendance — Perlu Tindakan</h1>
            <p>{data.period.label} · clock in/out kosong, lintas semua talent</p>
          </div>
        </div>

        <div className="summary-strip action-summary" aria-label="Attendance gaps summary">
          <div className="summary-item">
            <div className="summary-label">Gap terbuka</div>
            <div className="summary-value">{items?.length ?? "…"}</div>
            <div className="summary-meta">Clock in/out kosong bulan ini</div>
          </div>
        </div>

        {notice ? <div className="refresh-error" role="status">{notice}</div> : null}
        {error ? <div className="refresh-error" role="status">{error}</div> : null}

        <section className="panel action-queue-panel">
          <div className="panel-title-row">
            <div>
              <h2>Attendance gaps</h2>
              <span>{visible.length} baris perlu evidence + jam</span>
            </div>
          </div>
          <div className="toolbar action-toolbar">
            <div className="panel-search">
              <SearchIcon />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Cari nama talent" aria-label="Cari talent" />
            </div>
            <div className="attendance-gap-action-group attendance-gap-group-toggle" role="group" aria-label="Kelompokkan berdasarkan">
              <div>
                <button type="button" className={groupBy === "talent" ? "active" : ""} onClick={() => setGroupBy("talent")}>
                  Per Talent
                </button>
                <button type="button" className={groupBy === "date" ? "active" : ""} onClick={() => setGroupBy("date")}>
                  Per Tanggal
                </button>
              </div>
            </div>
          </div>

          {loading ? <div className="empty-state">Memuat…</div> : null}
          {!loading && visible.length === 0 ? <div className="empty-state">Tidak ada attendance gap ✓</div> : null}

          <div className="desktop-table-wrap">
            <table className="data-table action-table attendance-gap-table">
              <thead>
                <tr>
                  {groupBy === "date" ? <th>Talent</th> : null}
                  {groupBy === "talent" ? <th>Tanggal</th> : null}
                  <th>Gap</th>
                  <th aria-label="Aksi" />
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const collapsed = collapsedGroups.has(group.key);
                  return (
                    <Fragment key={group.key}>
                      <tr className="attendance-gap-group-header" onClick={() => toggleGroup(group.key)}>
                        <td colSpan={3}>
                          <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span> {group.label}
                          <span className="attendance-gap-group-count">{group.items.length} gap</span>
                        </td>
                      </tr>
                      {!collapsed
                        ? group.items.map((item) => {
                            const isOpen = openKey === item.attendance_key;
                            const draft = draftFor(item);
                            const bothMissing = item.gap === "missing_both";
                            const busy = busyKey === item.attendance_key;
                            return (
                              <Fragment key={item.attendance_key}>
                                <tr onClick={() => setOpenKey(isOpen ? null : item.attendance_key)}>
                                  {groupBy === "date" ? <td><div className="talent-name">{item.name}</div></td> : null}
                                  {groupBy === "talent" ? <td>{dateLabel(item.work_date)}</td> : null}
                                  <td>{gapLabel(item)}</td>
                                  <td><button className="secondary-button" type="button">{isOpen ? "Tutup" : "Upload + Isi"}</button></td>
                                </tr>
                                {isOpen ? (
                                  <tr className="attendance-gap-form-row" key={`${item.attendance_key}-form`}>
                                    <td colSpan={3}>
                            <div className="attendance-gap-form">
                              {bothMissing ? (
                                <div className="attendance-gap-action-group">
                                  <span>Apa yang terjadi?</span>
                                  <div>
                                    {(["worked", "sakit", "izin", "cuti", "libur"] as GapAction[]).map((action) => (
                                      <button
                                        type="button"
                                        key={action}
                                        className={draft.action === action ? "active" : ""}
                                        onClick={() => patchDraft(item, { action })}
                                      >
                                        {action === "worked" ? "Saya bekerja" : action.charAt(0).toUpperCase() + action.slice(1)}
                                      </button>
                                    ))}
                                  </div>
                                </div>
                              ) : null}

                              {draft.action === "worked" ? (
                                <div className="attendance-gap-time-grid">
                                  {item.gap === "missing_clock_in" || bothMissing ? (
                                    <label>
                                      Jam masuk
                                      <input type="time" value={draft.checkIn} onChange={(event) => patchDraft(item, { checkIn: event.target.value })} />
                                    </label>
                                  ) : null}
                                  {item.gap === "missing_clock_out" || bothMissing ? (
                                    <label>
                                      Jam pulang
                                      <input type="time" value={draft.checkOut} onChange={(event) => patchDraft(item, { checkOut: event.target.value })} />
                                    </label>
                                  ) : null}
                                </div>
                              ) : (
                                <div className="attendance-gap-time-grid">
                                  <label>
                                    Jam masuk (opsional)
                                    <input type="time" value={draft.checkIn} onChange={(event) => patchDraft(item, { checkIn: event.target.value })} />
                                  </label>
                                  <label>
                                    Jam pulang (opsional)
                                    <input type="time" value={draft.checkOut} onChange={(event) => patchDraft(item, { checkOut: event.target.value })} />
                                  </label>
                                </div>
                              )}

                              <label className="attendance-gap-file-row">
                                <input
                                  type="file"
                                  accept="image/jpeg,image/png,image/webp"
                                  disabled={busyKey !== null}
                                  onChange={(event) => patchDraft(item, { file: event.target.files?.[0] ?? null })}
                                />
                                <span>{draft.file ? draft.file.name : "+ Tambah Foto Evidence"}</span>
                              </label>

                              <button className="primary-button" type="button" disabled={busyKey !== null || !draft.file} onClick={() => void submit(item)}>
                                {busy ? "Menyimpan…" : "Simpan"}
                              </button>
                            </div>
                          </td>
                                </tr>
                                ) : null}
                              </Fragment>
                            );
                          })
                        : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mobile-operational-list action-mobile-list">
            {groups.map((group) => {
              const collapsed = collapsedGroups.has(group.key);
              return (
                <div className="attendance-gap-group" key={group.key}>
                  <button
                    type="button"
                    className="attendance-gap-group-header attendance-gap-group-header-mobile"
                    onClick={() => toggleGroup(group.key)}
                  >
                    <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span> {group.label}
                    <span className="attendance-gap-group-count">{group.items.length} gap</span>
                  </button>
                  {!collapsed
                    ? group.items.map((item) => {
                        const isOpen = openKey === item.attendance_key;
                        const draft = draftFor(item);
                        const bothMissing = item.gap === "missing_both";
                        const busy = busyKey === item.attendance_key;
                        return (
                          <div className="attendance-gap-mobile-item" key={item.attendance_key}>
                            <button className="mobile-attention-row action-mobile-row" type="button" onClick={() => setOpenKey(isOpen ? null : item.attendance_key)}>
                              {groupBy === "date" ? <div className="mobile-attention-name">{item.name}</div> : null}
                              <div className="mobile-attention-issue">
                                {groupBy === "talent" ? `${dateLabel(item.work_date)} · ` : null}
                                {gapLabel(item)}
                              </div>
                            </button>
                            {isOpen ? (
                    <div className="attendance-gap-form">
                      {bothMissing ? (
                        <div className="attendance-gap-action-group">
                          <span>Apa yang terjadi?</span>
                          <div>
                            {(["worked", "sakit", "izin", "cuti", "libur"] as GapAction[]).map((action) => (
                              <button
                                type="button"
                                key={action}
                                className={draft.action === action ? "active" : ""}
                                onClick={() => patchDraft(item, { action })}
                              >
                                {action === "worked" ? "Saya bekerja" : action.charAt(0).toUpperCase() + action.slice(1)}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {draft.action === "worked" ? (
                        <div className="attendance-gap-time-grid">
                          {item.gap === "missing_clock_in" || bothMissing ? (
                            <label>
                              Jam masuk
                              <input type="time" value={draft.checkIn} onChange={(event) => patchDraft(item, { checkIn: event.target.value })} />
                            </label>
                          ) : null}
                          {item.gap === "missing_clock_out" || bothMissing ? (
                            <label>
                              Jam pulang
                              <input type="time" value={draft.checkOut} onChange={(event) => patchDraft(item, { checkOut: event.target.value })} />
                            </label>
                          ) : null}
                        </div>
                      ) : (
                        <div className="attendance-gap-time-grid">
                          <label>
                            Jam masuk (opsional)
                            <input type="time" value={draft.checkIn} onChange={(event) => patchDraft(item, { checkIn: event.target.value })} />
                          </label>
                          <label>
                            Jam pulang (opsional)
                            <input type="time" value={draft.checkOut} onChange={(event) => patchDraft(item, { checkOut: event.target.value })} />
                          </label>
                        </div>
                      )}

                      <label className="attendance-gap-file-row">
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          disabled={busyKey !== null}
                          onChange={(event) => patchDraft(item, { file: event.target.files?.[0] ?? null })}
                        />
                        <span>{draft.file ? draft.file.name : "+ Tambah Foto Evidence"}</span>
                      </label>
                      <button className="primary-button" type="button" disabled={busyKey !== null || !draft.file} onClick={() => void submit(item)}>
                        {busy ? "Menyimpan…" : "Simpan"}
                      </button>
                            </div>
                          ) : null}
                          </div>
                        );
                      })
                    : null}
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </WorkspaceFrame>
  );
}
