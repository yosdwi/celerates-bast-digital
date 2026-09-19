import { useEffect, useState } from "react";
import {
  getPayrollClosingSettings,
  savePayrollClosingSettings,
} from "../api/payroll";
import type { PayrollClosingSettings } from "../api/payroll";
import type { TalentOpsSession } from "../api/types";

interface Props {
  session: TalentOpsSession;
}

const SUPPORTED_ROLES = ["Developer", "IoT Operations"] as const;

function isAdmin(session: TalentOpsSession): boolean {
  return ["owner", "admin"].includes(session.user.role.toLowerCase());
}

function parseOffsets(value: string): number[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => Number(item.trim()))
        .filter((offset) => Number.isInteger(offset) && offset >= 1 && offset <= 31),
    ),
  ).sort((a, b) => b - a);
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Jakarta",
  }).format(new Date(`${value}T00:00:00+07:00`));
}

export default function PayrollClosingPolicySettings({ session }: Props) {
  const admin = isAdmin(session);
  const [settings, setSettings] = useState<PayrollClosingSettings | null>(null);
  const [offsetText, setOffsetText] = useState("5, 3, 1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const value = await getPayrollClosingSettings();
      setSettings(value);
      setOffsetText(value.reminder_offsets.join(", "));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Payroll closing policy unavailable.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function save() {
    if (!admin || !settings || busy) return;
    const offsets = parseOffsets(offsetText);
    if (offsets.length === 0) {
      setError("Isi minimal satu milestone reminder, misalnya 5, 3, 1.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await savePayrollClosingSettings(
        session.csrf_token,
        {
          enabled: settings.enabled,
          paused: settings.paused,
          closing_day: settings.closing_day,
          reminder_hour: settings.reminder_hour,
          reminder_offsets: offsets,
          target_roles: settings.target_roles,
          next_day_ready_hour: settings.next_day_ready_hour,
        },
        settings.scope_key,
      );
      setSettings(saved);
      setOffsetText(saved.reminder_offsets.join(", "));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Payroll closing policy update failed.");
    } finally {
      setBusy(false);
    }
  }

  function toggleRole(role: string, checked: boolean) {
    if (!settings) return;
    const current = new Set(settings.target_roles);
    if (checked) current.add(role);
    else current.delete(role);
    setSettings({ ...settings, target_roles: Array.from(current) });
  }

  return (
    <section className="panel settings-card">
      <div className="panel-title-row">
        <div>
          <h2>Payroll closing automation</h2>
          <span>21–20 cycle · H-N reminder policy · deterministic attendance projection</span>
        </div>
        {admin && settings ? (
          <button className="primary-button" type="button" disabled={busy} onClick={() => void save()}>
            {busy ? "Saving…" : "Save Payroll policy"}
          </button>
        ) : null}
      </div>

      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}
      {!settings ? <div className="empty-state">Payroll closing policy unavailable.</div> : (
        <>
          <div className="workflow-form-grid">
            <label className="workflow-toggle">
              <input
                type="checkbox"
                checked={settings.enabled}
                disabled={!admin}
                onChange={(event) => setSettings({ ...settings, enabled: event.target.checked })}
              />
              Enable Payroll reminder campaign
            </label>
            <label className="workflow-toggle">
              <input
                type="checkbox"
                checked={settings.paused}
                disabled={!admin || !settings.enabled}
                onChange={(event) => setSettings({ ...settings, paused: event.target.checked })}
              />
              Pause campaign
            </label>
            <label>
              Closing day
              <input
                type="number"
                min={1}
                max={31}
                value={settings.closing_day}
                disabled={!admin}
                onChange={(event) => setSettings({ ...settings, closing_day: Number(event.target.value) })}
              />
            </label>
            <label>
              Reminder hour · WIB
              <input
                type="number"
                min={0}
                max={23}
                value={settings.reminder_hour}
                disabled={!admin}
                onChange={(event) => setSettings({ ...settings, reminder_hour: Number(event.target.value) })}
              />
            </label>
            <label>
              Milestones H-N
              <input
                value={offsetText}
                disabled={!admin}
                placeholder="5, 3, 1"
                onChange={(event) => setOffsetText(event.target.value)}
              />
            </label>
            <label>
              Previous day evaluable at · WIB
              <input
                type="number"
                min={0}
                max={23}
                value={settings.next_day_ready_hour}
                disabled={!admin}
                onChange={(event) => setSettings({ ...settings, next_day_ready_hour: Number(event.target.value) })}
              />
            </label>
          </div>

          <div className="approval-inline-actions" aria-label="Payroll reminder audience">
            {SUPPORTED_ROLES.map((role) => (
              <label className="workflow-toggle" key={role}>
                <input
                  type="checkbox"
                  checked={settings.target_roles.includes(role)}
                  disabled={!admin}
                  onChange={(event) => toggleRole(role, event.target.checked)}
                />
                {role}
              </label>
            ))}
          </div>

          <div className="settings-status">
            {settings.enabled ? (settings.paused ? "Enabled · paused" : "Enabled · active") : "Disabled · no scheduled Payroll sends"}
            {` · desired v${settings.desired_version} · applied v${settings.applied_version}`}
          </div>

          <div className="workflow-operator-list">
            <div className="workflow-operator-card">
              <div className="workflow-operator-head">
                <div>
                  <strong>{settings.preview.cycle.label}</strong>
                  <div className="cell-muted">
                    {dateLabel(settings.preview.cycle.start)} – {dateLabel(settings.preview.cycle.end)}
                  </div>
                  <div className="workflow-operator-meta">
                    {settings.preview.milestones.map((item) => (
                      <span key={item.label}>{item.label}: {dateLabel(item.work_date)}</span>
                    ))}
                  </div>
                </div>
                <div className="workflow-operator-meta">
                  <span>{settings.preview.estimated_actionable_talents} Talent estimated actionable</span>
                  <span>{settings.preview.estimated_unverified_talents} source perlu dicek</span>
                </div>
              </div>
            </div>
          </div>

          <p>
            Preview memakai closing projection saat ini. `Menunggu Review`, `Complete`, dan source teknis yang
            belum terverifikasi tidak dihitung sebagai Talent reminder action. Legacy BAST calendar reminders
            tetap terpisah sampai Payroll campaign diaktifkan.
          </p>
        </>
      )}
    </section>
  );
}
