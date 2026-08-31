import { useEffect, useState } from "react";
import {
  getNotificationSettings,
  getTalentMobileSettings,
  getWorkflowOperators,
  issueWorkflowOperatorInvite,
  saveNotificationSettings,
  saveTalentMobileSettings,
  saveWorkflowOperator,
  unlinkWorkflowOperatorWhatsApp,
} from "../api/talentops";
import type {
  NotificationSettings,
  TalentMobileSettings,
  TalentOpsSession,
  WhatsAppInvite,
  WorkflowOperator,
  WorkflowOperatorInput,
} from "../api/types";

interface Props {
  session: TalentOpsSession;
}

const EMPTY_OPERATOR: WorkflowOperatorInput = {
  display_name: "",
  scope_key: "default",
  active: true,
  can_approve_attendance: true,
  can_approve_rebind: true,
  can_generate_bast: true,
  whatsapp_notify: false,
};

function isAdmin(session: TalentOpsSession): boolean {
  return ["owner", "admin"].includes(session.user.role.toLowerCase());
}

function parseReminderDays(value: string): number[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => Number(item.trim()))
        .filter((day) => Number.isInteger(day) && day >= 1 && day <= 31),
    ),
  ).sort((a, b) => a - b);
}

export default function WorkflowSettings({ session }: Props) {
  const admin = isAdmin(session);
  const [operators, setOperators] = useState<WorkflowOperator[]>([]);
  const [notifications, setNotifications] = useState<NotificationSettings | null>(null);
  const [talentMobile, setTalentMobile] = useState<TalentMobileSettings | null>(null);
  const [form, setForm] = useState<WorkflowOperatorInput>(EMPTY_OPERATOR);
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState<WhatsAppInvite | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const notificationsPromise = getNotificationSettings();
    const operatorsPromise = admin ? getWorkflowOperators() : Promise.resolve([] as WorkflowOperator[]);
    const talentMobilePromise = admin ? getTalentMobileSettings() : Promise.resolve(null);
    try {
      const [notificationValue, operatorValue, talentMobileValue] = await Promise.all([
        notificationsPromise,
        operatorsPromise,
        talentMobilePromise,
      ]);
      setNotifications(notificationValue);
      setOperators(operatorValue);
      setTalentMobile(talentMobileValue);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workflow settings unavailable.");
    }
  }

  useEffect(() => {
    void load();
  }, [admin]);

  async function submitOperator() {
    if (!admin || !email.trim() || !form.display_name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveWorkflowOperator(session.csrf_token, email.trim(), form);
      setOperators((current) => {
        const without = current.filter((item) => item.email !== saved.email);
        return [saved, ...without];
      });
      setEmail("");
      setForm(EMPTY_OPERATOR);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "PMO provisioning failed.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleOperator(operator: WorkflowOperator, active: boolean) {
    if (!admin || busy) return;
    setBusy(true);
    try {
      const saved = await saveWorkflowOperator(session.csrf_token, operator.email, {
        display_name: operator.display_name,
        scope_key: operator.scope_key,
        active,
        can_approve_attendance: operator.can_approve_attendance,
        can_approve_rebind: operator.can_approve_rebind,
        can_generate_bast: operator.can_generate_bast,
        whatsapp_notify: operator.whatsapp_notify,
      });
      setOperators((current) => current.map((item) => item.email === saved.email ? saved : item));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Operator update failed.");
    } finally {
      setBusy(false);
    }
  }

  async function issueInvite(operator: WorkflowOperator) {
    if (!admin || busy) return;
    setBusy(true);
    setInvite(null);
    try {
      setInvite(await issueWorkflowOperatorInvite(session.csrf_token, operator.email));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "WhatsApp invite failed.");
    } finally {
      setBusy(false);
    }
  }

  async function unlink(operator: WorkflowOperator) {
    if (!admin || busy) return;
    setBusy(true);
    try {
      await unlinkWorkflowOperatorWhatsApp(session.csrf_token, operator.email);
      setOperators((current) => current.map((item) => item.email === operator.email ? { ...item, whatsapp_jid: null } : item));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "WhatsApp unlink failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveTalentMobileUrl() {
    if (!admin || !talentMobile || busy) return;
    setBusy(true);
    setError(null);
    try {
      const publicUrl = talentMobile.public_url?.trim() || null;
      setTalentMobile(
        await saveTalentMobileSettings(
          session.csrf_token,
          publicUrl,
          talentMobile.scope_key,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Talent Mobile URL update failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveNotifications() {
    if (!admin || !notifications || busy) return;
    setBusy(true);
    try {
      const { scope_key: scopeKey, ...input } = notifications;
      setNotifications(await saveNotificationSettings(session.csrf_token, input, scopeKey));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Reminder policy update failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workflow-settings-stack">
      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}

      {admin ? (
        <section className="panel settings-card">
          <div className="panel-title-row">
            <div>
              <h2>Talent Mobile</h2>
              <span>Public URL used in signed Attendance and Task Evidence links</span>
            </div>
            {talentMobile ? <button className="primary-button" type="button" disabled={busy} onClick={() => void saveTalentMobileUrl()}>Save URL</button> : null}
          </div>
          {talentMobile ? (
            <>
              <div className="workflow-form-grid">
                <label>Public URL<input type="url" value={talentMobile.public_url ?? ""} placeholder="https://talentops.example.com" onChange={(event) => setTalentMobile({ ...talentMobile, public_url: event.target.value })} /></label>
              </div>
              <p>Use the public origin of this TalentOps app only, without a path or query. HTTPS is required outside localhost. New WhatsApp links use the saved value immediately; the server environment value is only a fallback when this field is empty.</p>
              <div className="settings-status">{talentMobile.public_url ? "Configured · new Talent links use this URL" : "Not saved · environment fallback is used only if configured"}</div>
            </>
          ) : <div className="empty-state">Talent Mobile setting unavailable.</div>}
        </section>
      ) : null}

      <section className="panel settings-card">
        <div className="panel-title-row">
          <div>
            <h2>WhatsApp reminders</h2>
            <span>Choose calendar dates separately for Talent and PMO</span>
          </div>
          {admin && notifications ? <button className="primary-button" type="button" disabled={busy} onClick={() => void saveNotifications()}>Save policy</button> : null}
        </div>
        {notifications ? (
          <div className="workflow-form-grid">
            <label>Scope<input value={notifications.scope_key} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, scope_key: event.target.value })} /></label>
            <label>Reminder hour<input type="number" min={0} max={23} value={notifications.reminder_hour} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, reminder_hour: Number(event.target.value) })} /></label>
            <label>Talent reminder dates<input value={notifications.talent_reminder_days.join(", ")} placeholder="20, 25, 28" disabled={!admin} onChange={(event) => setNotifications({ ...notifications, talent_reminder_days: parseReminderDays(event.target.value) })} /></label>
            <label>PMO reminder dates<input value={notifications.pmo_reminder_days.join(", ")} placeholder="27, 29, 30" disabled={!admin} onChange={(event) => setNotifications({ ...notifications, pmo_reminder_days: parseReminderDays(event.target.value) })} /></label>
            <label className="workflow-toggle"><input type="checkbox" checked={notifications.attendance_immediate} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, attendance_immediate: event.target.checked })} />Immediate attendance approval alert</label>
            <label className="workflow-toggle"><input type="checkbox" checked={notifications.rebind_immediate} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, rebind_immediate: event.target.checked })} />Immediate rebind alert</label>
          </div>
        ) : <div className="empty-state">Reminder policy unavailable.</div>}
        <p>
          Dates are day-of-month values. On a configured date, Talent is reminded only when
          personal BAST work is still outstanding; PMO is reminded only when its shared queue
          still needs action. Empty dates mean no scheduled reminder for that audience.
        </p>
      </section>

      {admin ? (
        <section className="panel settings-card">
          <div className="panel-title-row"><div><h2>PMO access</h2><span>Admin-provisioned only · no self-service role selection in WhatsApp</span></div></div>
          <div className="workflow-form-grid">
            <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="pmo@celerates.co.id" /></label>
            <label>Display name<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label>
            <label>Scope<input value={form.scope_key} onChange={(event) => setForm({ ...form, scope_key: event.target.value })} /></label>
            <label className="workflow-toggle"><input type="checkbox" checked={form.can_approve_attendance} onChange={(event) => setForm({ ...form, can_approve_attendance: event.target.checked })} />Attendance approval</label>
            <label className="workflow-toggle"><input type="checkbox" checked={form.can_approve_rebind} onChange={(event) => setForm({ ...form, can_approve_rebind: event.target.checked })} />Rebind approval</label>
            <label className="workflow-toggle"><input type="checkbox" checked={form.can_generate_bast} onChange={(event) => setForm({ ...form, can_generate_bast: event.target.checked })} />BAST generation</label>
            <label className="workflow-toggle"><input type="checkbox" checked={form.whatsapp_notify} onChange={(event) => setForm({ ...form, whatsapp_notify: event.target.checked })} />Receive WhatsApp notifications</label>
          </div>
          <div className="approval-inline-actions">
            <button className="primary-button" type="button" disabled={busy || !email.trim() || !form.display_name.trim()} onClick={() => void submitOperator()}>Provision PMO</button>
          </div>

          <div className="workflow-operator-list">
            {operators.map((operator) => (
              <div className="workflow-operator-card" key={operator.email}>
                <div className="workflow-operator-head">
                  <div>
                    <strong>{operator.display_name}</strong>
                    <div className="cell-muted">{operator.email}</div>
                    <div className="workflow-operator-meta">
                      <span>{operator.active ? "Active" : "Inactive"}</span>
                      <span>Scope: {operator.scope_key}</span>
                      <span>Attendance: {operator.can_approve_attendance ? "yes" : "no"}</span>
                      <span>Rebind: {operator.can_approve_rebind ? "yes" : "no"}</span>
                      <span>BAST: {operator.can_generate_bast ? "yes" : "no"}</span>
                      <span>WA: {operator.whatsapp_jid ? "linked" : "not linked"}</span>
                    </div>
                  </div>
                  <div className="approval-inline-actions">
                    <button className="secondary-button" type="button" disabled={busy || !operator.active} onClick={() => void issueInvite(operator)}>Issue WA invite</button>
                    {operator.whatsapp_jid ? <button className="secondary-button" type="button" disabled={busy} onClick={() => void unlink(operator)}>Unlink WA</button> : null}
                    <button className="secondary-button" type="button" disabled={busy} onClick={() => void toggleOperator(operator, !operator.active)}>{operator.active ? "Deactivate" : "Activate"}</button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {invite ? (
            <div className="workflow-invite-token" role="status">
              Send this one-time token privately to {invite.operator_email}:<br />
              <strong>{invite.token}</strong><br />
              Expires {new Date(invite.expires_at).toLocaleString()}.
            </div>
          ) : null}
        </section>
      ) : (
        <section className="panel settings-card">
          <div className="panel-title-row"><div><h2>PMO access</h2><span>Managed by Admin</span></div></div>
          <p>Your PMO permissions and WhatsApp linking are provisioned centrally. This page never offers self-service PMO role escalation.</p>
        </section>
      )}
    </div>
  );
}
