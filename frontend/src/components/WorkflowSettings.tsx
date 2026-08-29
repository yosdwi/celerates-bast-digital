import { useEffect, useState } from "react";
import {
  getNotificationSettings,
  getWorkflowOperators,
  issueWorkflowOperatorInvite,
  saveNotificationSettings,
  saveWorkflowOperator,
  unlinkWorkflowOperatorWhatsApp,
} from "../api/talentops";
import type {
  NotificationSettings,
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

export default function WorkflowSettings({ session }: Props) {
  const admin = isAdmin(session);
  const [operators, setOperators] = useState<WorkflowOperator[]>([]);
  const [notifications, setNotifications] = useState<NotificationSettings | null>(null);
  const [form, setForm] = useState<WorkflowOperatorInput>(EMPTY_OPERATOR);
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState<WhatsAppInvite | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const notificationsPromise = getNotificationSettings();
    const operatorsPromise = admin ? getWorkflowOperators() : Promise.resolve([] as WorkflowOperator[]);
    try {
      const [notificationValue, operatorValue] = await Promise.all([
        notificationsPromise,
        operatorsPromise,
      ]);
      setNotifications(notificationValue);
      setOperators(operatorValue);
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

  async function saveNotifications() {
    if (!admin || !notifications || busy) return;
    setBusy(true);
    try {
      const { scope_key: scopeKey, ...input } = notifications;
      setNotifications(await saveNotificationSettings(session.csrf_token, input, scopeKey));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Notification settings update failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workflow-settings-stack">
      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}

      <section className="panel settings-card">
        <div className="panel-title-row">
          <div><h2>Workflow notifications</h2><span>Routing is separate from approval authority</span></div>
          {admin && notifications ? <button className="primary-button" type="button" disabled={busy} onClick={() => void saveNotifications()}>Save policy</button> : null}
        </div>
        {notifications ? (
          <div className="workflow-form-grid">
            <label>Scope<input value={notifications.scope_key} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, scope_key: event.target.value })} /></label>
            <label>Digest hour<input type="number" min={0} max={23} value={notifications.digest_hour} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, digest_hour: Number(event.target.value) })} /></label>
            <label>Deadline reminder days<input value={notifications.deadline_reminder_days.join(", ")} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, deadline_reminder_days: event.target.value.split(",").map((value) => Number(value.trim())).filter(Number.isFinite) })} /></label>
            <label className="workflow-toggle"><input type="checkbox" checked={notifications.digest_enabled} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, digest_enabled: event.target.checked })} />Daily digest</label>
            <label className="workflow-toggle"><input type="checkbox" checked={notifications.attendance_immediate} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, attendance_immediate: event.target.checked })} />Immediate attendance approval alert</label>
            <label className="workflow-toggle"><input type="checkbox" checked={notifications.rebind_immediate} disabled={!admin} onChange={(event) => setNotifications({ ...notifications, rebind_immediate: event.target.checked })} />Immediate rebind alert</label>
          </div>
        ) : <div className="empty-state">Notification policy unavailable.</div>}
        <p>Default behavior is digest/deadline-oriented to avoid one WhatsApp notification per Talent action.</p>
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
