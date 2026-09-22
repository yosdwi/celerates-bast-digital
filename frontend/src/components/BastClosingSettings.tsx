import { useEffect, useMemo, useState } from "react";
import {
  getBastClosingSettings,
  getBastEvidenceRules,
  previewBastBlast,
  saveBastClosingSettings,
  saveBastEvidenceRules,
  sendBastBlast,
} from "../api/bastClosing";
import type {
  BastBlastPreview,
  BastClosingSettings as BastClosingSettingsData,
  BastManualBlastResult,
  EvidenceRule,
} from "../api/bastClosing";
import type { TalentOpsSession } from "../api/types";

interface Props {
  session: TalentOpsSession;
  period: { year: number; month: number };
}

export default function BastClosingSettings({ session, period }: Props) {
  const [settings, setSettings] = useState<BastClosingSettingsData | null>(null);
  const [rules, setRules] = useState<EvidenceRule[]>([]);
  const [preview, setPreview] = useState<BastBlastPreview | null>(null);
  const [result, setResult] = useState<BastManualBlastResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = useMemo(
    () => ["owner", "admin"].includes(session.user.role.toLowerCase()),
    [session.user.role],
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextSettings, nextRules] = await Promise.all([
        getBastClosingSettings(period.year, period.month),
        getBastEvidenceRules(),
      ]);
      setSettings(nextSettings);
      setRules(nextRules.rules);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load BAST Closing settings.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [period.year, period.month]);

  async function save() {
    if (!settings || !isAdmin || saving) return;
    setSaving(true);
    setError(null);
    try {
      await Promise.all([
        saveBastClosingSettings(session.csrf_token, {
          enabled: settings.enabled,
          initial_day: settings.initial_day,
          followup_offsets: settings.followup_offsets,
          send_hour: settings.send_hour,
          talent_reminder_enabled: settings.talent_reminder_enabled,
          pmo_summary_enabled: settings.pmo_summary_enabled,
          pmo_group_jid: settings.pmo_group_jid,
        }),
        saveBastEvidenceRules(session.csrf_token, rules),
      ]);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save BAST Closing settings.");
    } finally {
      setSaving(false);
    }
  }

  async function previewBlast() {
    setError(null);
    setResult(null);
    try {
      setPreview(await previewBastBlast(period.year, period.month));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to preview BAST blast.");
    }
  }

  async function sendBlast() {
    if (!preview || preview.will_send === 0 || sending) return;
    if (!window.confirm(`Kirim reminder BAST ke ${preview.will_send} Talent sekarang?`)) return;
    setSending(true);
    setError(null);
    try {
      const next = await sendBastBlast(session.csrf_token, period.year, period.month);
      setResult(next);
      setPreview(await previewBastBlast(period.year, period.month));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to send BAST blast.");
    } finally {
      setSending(false);
    }
  }

  if (loading) {
    return <section className="panel settings-card"><h2>BAST Closing</h2><p>Loading configuration…</p></section>;
  }
  if (!settings) {
    return <section className="panel settings-card"><h2>BAST Closing</h2><p>{error ?? "Configuration unavailable."}</p></section>;
  }

  return (
    <section className="panel settings-card bast-closing-settings">
      <div className="panel-title-row">
        <div>
          <h2>BAST Closing</h2>
          <span>Schedule, evidence rules, dan manual reminder Talent</span>
        </div>
        <label>
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={!isAdmin}
            onChange={(event) => setSettings({ ...settings, enabled: event.target.checked })}
          /> Campaign {settings.enabled ? "ON" : "OFF"}
        </label>
      </div>

      {error ? <div className="refresh-error" role="status">{error}</div> : null}

      <div className="settings-grid">
        <div>
          <h3>Schedule</h3>
          <label>
            Initial reminder day
            <input
              type="number"
              min={1}
              max={31}
              value={settings.initial_day}
              disabled={!isAdmin}
              onChange={(event) => setSettings({ ...settings, initial_day: Number(event.target.value) })}
            />
          </label>
          <label>
            Send hour (WIB)
            <input
              type="number"
              min={0}
              max={23}
              value={settings.send_hour}
              disabled={!isAdmin}
              onChange={(event) => setSettings({ ...settings, send_hour: Number(event.target.value) })}
            />
          </label>
          <p>Follow-up: EOM - {settings.followup_offsets.join(" dan EOM - ")} hari.</p>
          <p>
            Next dates: {settings.schedule.talent_reminder_dates.join(", ")} · Closing {settings.schedule.closing}
          </p>
        </div>

        <div>
          <h3>Notification</h3>
          <label>
            <input
              type="checkbox"
              checked={settings.talent_reminder_enabled}
              disabled={!isAdmin}
              onChange={(event) => setSettings({ ...settings, talent_reminder_enabled: event.target.checked })}
            /> Talent reminder
          </label>
          <label>
            <input
              type="checkbox"
              checked={settings.pmo_summary_enabled}
              disabled={!isAdmin}
              onChange={(event) => setSettings({ ...settings, pmo_summary_enabled: event.target.checked })}
            /> PMO summary
          </label>
          <label>
            PMO group JID
            <input
              type="text"
              value={settings.pmo_group_jid ?? ""}
              disabled={!isAdmin}
              onChange={(event) => setSettings({ ...settings, pmo_group_jid: event.target.value || null })}
            />
          </label>
        </div>
      </div>

      <div>
        <h3>Evidence Rules</h3>
        <p>Default task/category yang tidak dikonfigurasi: evidence tidak wajib.</p>
        {rules.map((rule, index) => (
          <label key={rule.task_category} className="settings-status">
            <input
              type="checkbox"
              checked={rule.evidence_required}
              disabled={!isAdmin}
              onChange={(event) => {
                const next = [...rules];
                next[index] = { ...rule, evidence_required: event.target.checked };
                setRules(next);
              }}
            /> {rule.task_category} — {rule.evidence_required ? "Required" : "Not required"}
          </label>
        ))}
      </div>

      {isAdmin ? (
        <button className="secondary-button" type="button" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save BAST Configuration"}
        </button>
      ) : null}

      <div>
        <h3>Manual Blast</h3>
        <p>Preview selalu menghitung ulang blocker aktual. Waiting PMO, Complete, dan source-review tidak diblast sebagai action Talent.</p>
        <button className="secondary-button" type="button" onClick={() => void previewBlast()}>
          Preview Blast
        </button>
        {preview ? (
          <>
            <div className="settings-status">
              Will send {preview.will_send} · Waiting PMO {preview.waiting_pmo} · Complete {preview.complete} · Source review {preview.source_review}
            </div>
            {preview.rows.filter((row) => row.status === "will_send").slice(0, 8).map((row) => (
              <p key={row.nrp}>{row.name} · {row.actionable_count} action</p>
            ))}
            <button
              className="primary-button"
              type="button"
              disabled={preview.will_send === 0 || sending}
              onClick={() => void sendBlast()}
            >
              {sending ? "Sending…" : `Send Blast to ${preview.will_send} Talent`}
            </button>
          </>
        ) : null}
        {result ? (
          <div className="settings-status">
            Sent {result.sent} · Skipped {result.skipped} · Failed {result.failed}
            {result.scheduled_slot_consumed ? " · Scheduled slot fulfilled" : " · Ad-hoc manual batch"}
          </div>
        ) : null}
      </div>
    </section>
  );
}
