import { useEffect, useMemo, useState } from "react";
import {
  approveAttendanceResolution,
  approveIdentityRebind,
  attendanceResolutionEvidenceUrl,
  getAttendanceResolutions,
  getIdentityRebinds,
  rejectAttendanceResolution,
  rejectIdentityRebind,
} from "../api/talentops";
import type {
  AttendanceResolution,
  IdentityRebindRequest,
  TalentOpsSession,
} from "../api/types";

interface Props {
  session: TalentOpsSession;
}

type RejectTarget =
  | { kind: "attendance"; id: string; label: string }
  | { kind: "rebind"; id: string; label: string }
  | null;

function timeLabel(value: string | null): string {
  return value ? value.slice(0, 5) : "-";
}

function attendanceChange(item: AttendanceResolution): string {
  if (item.resolution_type === "missing_clock_in") return `Clock In → ${timeLabel(item.proposed_check_in)}`;
  if (item.resolution_type === "missing_clock_out") return `Clock Out → ${timeLabel(item.proposed_check_out)}`;
  if (item.resolution_type === "missing_both_worked") {
    return `Clock In ${timeLabel(item.proposed_check_in)} · Clock Out ${timeLabel(item.proposed_check_out)}`;
  }
  return item.absence_type ? item.absence_type[0].toUpperCase() + item.absence_type.slice(1) : "Absence";
}

function maskJid(jid: string): string {
  const number = jid.split("@", 1)[0];
  if (number.length <= 6) return number;
  return `${number.slice(0, 3)}***${number.slice(-3)}`;
}

export default function ApprovalQueue({ session }: Props) {
  const [attendance, setAttendance] = useState<AttendanceResolution[]>([]);
  const [rebinds, setRebinds] = useState<IdentityRebindRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<RejectTarget>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [attendanceAllowed, setAttendanceAllowed] = useState(true);
  const [rebindAllowed, setRebindAllowed] = useState(true);

  const total = attendance.length + rebinds.length;
  const hasAnyCapability = attendanceAllowed || rebindAllowed;

  async function refresh() {
    setLoading(true);
    setError(null);
    const [attendanceResult, rebindResult] = await Promise.allSettled([
      getAttendanceResolutions(),
      getIdentityRebinds(),
    ]);
    if (attendanceResult.status === "fulfilled") {
      setAttendance(attendanceResult.value);
      setAttendanceAllowed(true);
    } else {
      setAttendance([]);
      setAttendanceAllowed(false);
    }
    if (rebindResult.status === "fulfilled") {
      setRebinds(rebindResult.value);
      setRebindAllowed(true);
    } else {
      setRebinds([]);
      setRebindAllowed(false);
    }
    if (attendanceResult.status === "rejected" && rebindResult.status === "rejected") {
      setError("Approval queue is unavailable for this session or temporarily unreachable.");
    }
    setLoading(false);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function approveAttendance(item: AttendanceResolution) {
    setBusyId(item.id);
    setError(null);
    try {
      await approveAttendanceResolution(session.csrf_token, item.id);
      setAttendance((current) => current.filter((entry) => entry.id !== item.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Attendance approval failed.");
      await refresh();
    } finally {
      setBusyId(null);
    }
  }

  async function approveRebind(item: IdentityRebindRequest) {
    setBusyId(item.id);
    setError(null);
    try {
      await approveIdentityRebind(session.csrf_token, item.id);
      setRebinds((current) => current.filter((entry) => entry.id !== item.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Rebind approval failed.");
      await refresh();
    } finally {
      setBusyId(null);
    }
  }

  async function confirmReject() {
    if (!rejectTarget || !rejectReason.trim()) return;
    setBusyId(rejectTarget.id);
    setError(null);
    try {
      if (rejectTarget.kind === "attendance") {
        await rejectAttendanceResolution(session.csrf_token, rejectTarget.id, rejectReason.trim());
        setAttendance((current) => current.filter((entry) => entry.id !== rejectTarget.id));
      } else {
        await rejectIdentityRebind(session.csrf_token, rejectTarget.id, rejectReason.trim());
        setRebinds((current) => current.filter((entry) => entry.id !== rejectTarget.id));
      }
      setRejectTarget(null);
      setRejectReason("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reject failed.");
      await refresh();
    } finally {
      setBusyId(null);
    }
  }

  const attendanceRows = useMemo(
    () => attendance.map((item) => ({ ...item, change: attendanceChange(item) })),
    [attendance],
  );

  if (!hasAnyCapability && !error) return null;

  return (
    <section className="panel approval-queue-panel">
      <div className="panel-title-row">
        <div>
          <h2>Approval queue</h2>
          <span>{loading ? "Loading shared workflow queue…" : `${total} pending requests · same state as WhatsApp PMO`}</span>
        </div>
        <button className="secondary-button" type="button" disabled={loading || busyId !== null} onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}
      {!loading && total === 0 && hasAnyCapability ? (
        <div className="empty-state">No approval requests are pending.</div>
      ) : null}

      {attendanceAllowed && attendanceRows.length > 0 ? (
        <div className="approval-group">
          <h3>Attendance gap resolution</h3>
          <p className="cell-muted">Raw client timestamps remain immutable. Approval validates only the proposed resolution / CSV projection.</p>
          <div className="approval-card-grid">
            {attendanceRows.map((item) => (
              <article className="approval-card" key={item.id}>
                <div className="approval-card-evidence">
                  <img
                    src={attendanceResolutionEvidenceUrl(item.id)}
                    alt={`Attendance evidence for ${item.full_name}`}
                    loading="lazy"
                  />
                </div>
                <div className="approval-card-body">
                  <div className="talent-name">{item.full_name}</div>
                  <div className="cell-muted">{item.nrp} · {item.work_date}</div>
                  <strong>{item.change}</strong>
                  <div className="cell-muted">Request {item.id.slice(0, 8)}</div>
                </div>
                <div className="approval-card-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => setRejectTarget({ kind: "attendance", id: item.id, label: `${item.full_name} · ${item.work_date}` })}
                  >
                    Reject
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => void approveAttendance(item)}
                  >
                    {busyId === item.id ? "Processing…" : "Approve"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {rebindAllowed && rebinds.length > 0 ? (
        <div className="approval-group">
          <h3>WhatsApp number replacement</h3>
          <p className="cell-muted">The old number stays authoritative until approval succeeds.</p>
          <div className="desktop-table-wrap">
            <table className="data-table">
              <thead><tr><th>Talent</th><th>Old binding</th><th>New binding</th><th>Requested</th><th>Action</th></tr></thead>
              <tbody>
                {rebinds.map((item) => (
                  <tr key={item.id}>
                    <td><div className="talent-name">{item.full_name}</div><div className="cell-muted">{item.nrp}</div></td>
                    <td>{maskJid(item.old_wa_jid)}</td>
                    <td>{maskJid(item.new_wa_jid)}</td>
                    <td>{new Date(item.requested_at).toLocaleString()}</td>
                    <td>
                      <div className="approval-inline-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={busyId !== null}
                          onClick={() => setRejectTarget({ kind: "rebind", id: item.id, label: item.full_name })}
                        >Reject</button>
                        <button
                          className="primary-button"
                          type="button"
                          disabled={busyId !== null}
                          onClick={() => void approveRebind(item)}
                        >{busyId === item.id ? "Processing…" : "Approve"}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {rejectTarget ? (
        <div className="approval-reject-box">
          <label htmlFor="approval-reject-reason">Reject reason · {rejectTarget.label}</label>
          <textarea
            id="approval-reject-reason"
            rows={3}
            maxLength={500}
            value={rejectReason}
            onChange={(event) => setRejectReason(event.target.value)}
            placeholder="Reason is required and will remain in the audit trail."
          />
          <div className="approval-inline-actions">
            <button className="secondary-button" type="button" disabled={busyId !== null} onClick={() => { setRejectTarget(null); setRejectReason(""); }}>Cancel</button>
            <button className="primary-button" type="button" disabled={!rejectReason.trim() || busyId !== null} onClick={() => void confirmReject()}>Confirm reject</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
