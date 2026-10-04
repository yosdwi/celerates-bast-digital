import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { TalentOpsSession } from "../api/types";

const BASE = "/api/talentops/v1/whatsapp-directory";

interface GroupParticipant {
  jid: string;
  is_admin: boolean;
  is_super_admin: boolean;
  employee_id: string | null;
  nrp: string | null;
  full_name: string | null;
  display_name?: string | null;
}

interface WhatsAppGroup {
  jid: string;
  subject: string;
  member_count: number;
  participants: GroupParticipant[];
}

interface TalentDirectoryItem {
  employee_id: string;
  nrp: string;
  full_name: string;
  role: string;
  wa_jid: string | null;
  bound_at: string | null;
  discovered_in_groups: boolean;
}

interface WhatsAppDirectory {
  ready: boolean;
  connection: string;
  discovered_at: string | null;
  groups: WhatsAppGroup[];
  talents: TalentDirectoryItem[];
}

interface ClosingGroup {
  scope_key: string;
  group_jid: string | null;
  bridge_ready: boolean;
  verified: boolean;
  group_subject: string | null;
}

interface MappingResponse {
  outcome: string;
  employee_id: string;
  wa_jid: string | null;
}

interface ContactOption {
  jid: string;
  displayName: string;
  groups: string[];
  mappedEmployeeId: string | null;
}

interface Props {
  session: TalentOpsSession;
}

function isAdmin(session: TalentOpsSession): boolean {
  return ["owner", "admin"].includes(session.user.role.toLowerCase());
}

function contactLabel(contact: ContactOption): string {
  if (contact.displayName && contact.displayName !== contact.jid) {
    return `${contact.displayName} · ${contact.jid}`;
  }
  return contact.jid;
}

export default function WhatsAppDirectorySettings({ session }: Props) {
  const admin = isAdmin(session);
  const [directory, setDirectory] = useState<WhatsAppDirectory | null>(null);
  const [closingGroup, setClosingGroup] = useState<ClosingGroup | null>(null);
  const [closingGroupDraft, setClosingGroupDraft] = useState("");
  const [mappingDraft, setMappingDraft] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [directoryValue, closingValue] = await Promise.all([
        apiFetch<WhatsAppDirectory>(BASE),
        apiFetch<ClosingGroup>(`${BASE}/closing-group`),
      ]);
      setDirectory(directoryValue);
      setClosingGroup(closingValue);
      setClosingGroupDraft(closingValue.group_jid ?? "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "WhatsApp directory unavailable.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const contacts = useMemo<ContactOption[]>(() => {
    if (!directory) return [];
    const byJid = new Map<string, ContactOption>();
    for (const group of directory.groups) {
      for (const participant of group.participants) {
        if (!participant.jid.endsWith("@c.us") && !participant.jid.endsWith("@lid")) continue;
        const current = byJid.get(participant.jid);
        const name = participant.full_name ?? participant.display_name ?? participant.jid;
        if (current) {
          if (!current.groups.includes(group.subject)) current.groups.push(group.subject);
          if (!current.mappedEmployeeId && participant.employee_id) {
            current.mappedEmployeeId = participant.employee_id;
          }
        } else {
          byJid.set(participant.jid, {
            jid: participant.jid,
            displayName: name,
            groups: [group.subject],
            mappedEmployeeId: participant.employee_id,
          });
        }
      }
    }
    return Array.from(byJid.values()).sort((left, right) =>
      left.displayName.localeCompare(right.displayName),
    );
  }, [directory]);

  async function bind(talent: TalentDirectoryItem) {
    const jid = mappingDraft[talent.employee_id]?.trim();
    if (!admin || !jid || busyKey) return;
    setBusyKey(talent.employee_id);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<MappingResponse>(
        `${BASE}/mappings/${encodeURIComponent(talent.employee_id)}`,
        {
          method: "PUT",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({ wa_jid: jid }),
        },
      );
      setNotice(
        result.outcome === "unchanged"
          ? `${talent.full_name} sudah terhubung ke identitas WhatsApp tersebut.`
          : `${talent.full_name} berhasil dihubungkan ke WhatsApp.`,
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Talent mapping failed.");
    } finally {
      setBusyKey(null);
    }
  }

  async function unbind(talent: TalentDirectoryItem) {
    if (!admin || !talent.wa_jid || busyKey) return;
    setBusyKey(talent.employee_id);
    setError(null);
    setNotice(null);
    try {
      await apiFetch<MappingResponse>(
        `${BASE}/mappings/${encodeURIComponent(talent.employee_id)}`,
        {
          method: "DELETE",
          headers: { "X-CSRF-Token": session.csrf_token },
        },
      );
      setNotice(`${talent.full_name} dilepas dari identitas WhatsApp sebelumnya.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Talent unlink failed.");
    } finally {
      setBusyKey(null);
    }
  }

  async function saveClosingGroup() {
    if (!admin || busyKey) return;
    setBusyKey("closing-group");
    setError(null);
    setNotice(null);
    try {
      const saved = await apiFetch<ClosingGroup>(`${BASE}/closing-group`, {
        method: "PUT",
        headers: { "X-CSRF-Token": session.csrf_token },
        body: JSON.stringify({ group_jid: closingGroupDraft.trim() || null }),
      });
      setClosingGroup(saved);
      setClosingGroupDraft(saved.group_jid ?? "");
      setNotice(
        saved.group_jid
          ? `Closing group disimpan${saved.verified ? " dan terverifikasi pada session aktif" : ""}.`
          : "Closing group dinonaktifkan.",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Closing group update failed.");
    } finally {
      setBusyKey(null);
    }
  }

  const mappedCount = directory?.talents.filter((talent) => talent.wa_jid).length ?? 0;
  const unmappedCount = (directory?.talents.length ?? 0) - mappedCount;

  return (
    <section className="panel settings-card whatsapp-directory-card">
      <div className="panel-title-row whatsapp-directory-title">
        <div>
          <h2>Contacts &amp; WhatsApp</h2>
          <span>Real group discovery, Talent identity mapping, and Payroll closing destination</span>
        </div>
        <button className="secondary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void load()}>
          Refresh discovery
        </button>
      </div>

      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}
      {notice ? <div className="settings-status" role="status">{notice}</div> : null}

      <div className="whatsapp-directory-summary">
        <div><span>Session</span><strong>{directory?.ready ? "Connected" : directory?.connection ?? "Loading…"}</strong></div>
        <div><span>Groups</span><strong>{directory?.groups.length ?? "—"}</strong></div>
        <div><span>Talent mapped</span><strong>{mappedCount}</strong></div>
        <div><span>Need mapping</span><strong>{unmappedCount}</strong></div>
      </div>

      <div className="whatsapp-directory-layout">
        <div className="whatsapp-directory-column">
          <div className="whatsapp-directory-section-head">
            <div><strong>Payroll closing group</strong><span>Only this saved group becomes the destination authority for later Payroll digest delivery.</span></div>
          </div>
          <div className="whatsapp-closing-control">
            <select
              value={closingGroupDraft}
              disabled={!admin || Boolean(busyKey)}
              onChange={(event) => setClosingGroupDraft(event.target.value)}
              aria-label="Payroll closing group"
            >
              <option value="">No closing group</option>
              {closingGroupDraft && !directory?.groups.some((group) => group.jid === closingGroupDraft) ? (
                <option value={closingGroupDraft}>{closingGroup?.group_subject ?? "Saved group"} · not in current snapshot</option>
              ) : null}
              {directory?.groups.map((group) => (
                <option key={group.jid} value={group.jid}>{group.subject || group.jid} · {group.member_count} members</option>
              ))}
            </select>
            {admin ? (
              <button className="primary-button" type="button" disabled={Boolean(busyKey)} onClick={() => void saveClosingGroup()}>
                Save group
              </button>
            ) : null}
          </div>
          <div className={`whatsapp-closing-state ${closingGroup?.verified ? "verified" : ""}`}>
            {closingGroup?.group_jid
              ? closingGroup.verified
                ? `Verified · ${closingGroup.group_subject ?? closingGroup.group_jid}`
                : `Saved · ${closingGroup.group_jid} · current session has not verified it`
              : "No Payroll closing group selected"}
          </div>

          <div className="whatsapp-directory-section-head">
            <div><strong>Discovered groups</strong><span>Read live from the currently authenticated whatsapp-web.js session.</span></div>
          </div>
          <div className="whatsapp-group-list">
            {directory?.groups.map((group) => (
              <details key={group.jid} className="whatsapp-group-card">
                <summary>
                  <span><strong>{group.subject || "Unnamed group"}</strong><small>{group.jid}</small></span>
                  <b>{group.member_count}</b>
                </summary>
                <div className="whatsapp-member-list">
                  {group.participants.map((participant) => (
                    <div key={participant.jid} className="whatsapp-member-row">
                      <span>
                        <strong>{participant.full_name ?? participant.display_name ?? participant.jid}</strong>
                        {(participant.full_name || participant.display_name) ? <small>{participant.jid}</small> : null}
                      </span>
                      <span className={participant.employee_id ? "mapping-pill mapped" : "mapping-pill"}>
                        {participant.employee_id ? `Mapped · ${participant.nrp ?? "Talent"}` : "Unmapped"}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            ))}
            {directory && directory.groups.length === 0 ? (
              <div className="empty-state">No groups are available from the active WhatsApp session.</div>
            ) : null}
          </div>
        </div>

        <div className="whatsapp-directory-column">
          <div className="whatsapp-directory-section-head">
            <div><strong>Talent identity mapping</strong><span>Bind an active Talent to one exact WhatsApp identity. Conflicts never auto-reassign.</span></div>
          </div>
          <div className="whatsapp-talent-list">
            {directory?.talents.map((talent) => {
              const currentContact = contacts.find((contact) => contact.jid === talent.wa_jid);
              const options = contacts.filter(
                (contact) => !contact.mappedEmployeeId || contact.mappedEmployeeId === talent.employee_id,
              );
              return (
                <div className="whatsapp-talent-row" key={talent.employee_id}>
                  <div className="whatsapp-talent-identity">
                    <strong>{talent.full_name}</strong>
                    <span>{talent.nrp} · {talent.role}</span>
                    {talent.wa_jid ? (
                      <small>
                        {currentContact ? contactLabel(currentContact) : talent.wa_jid}
                        {talent.discovered_in_groups ? " · discovered" : " · not in current group snapshot"}
                      </small>
                    ) : <small>Not mapped</small>}
                  </div>
                  {admin ? (
                    talent.wa_jid ? (
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={Boolean(busyKey)}
                        onClick={() => void unbind(talent)}
                      >
                        Unlink
                      </button>
                    ) : (
                      <div className="whatsapp-map-control">
                        <select
                          value={mappingDraft[talent.employee_id] ?? ""}
                          disabled={Boolean(busyKey)}
                          onChange={(event) => setMappingDraft((current) => ({
                            ...current,
                            [talent.employee_id]: event.target.value,
                          }))}
                          aria-label={`WhatsApp identity for ${talent.full_name}`}
                        >
                          <option value="">Select discovered contact</option>
                          {options.map((contact) => (
                            <option key={contact.jid} value={contact.jid}>
                              {contactLabel(contact)} · {contact.groups.join(", ")}
                            </option>
                          ))}
                        </select>
                        <button
                          className="primary-button"
                          type="button"
                          disabled={Boolean(busyKey) || !(mappingDraft[talent.employee_id]?.trim())}
                          onClick={() => void bind(talent)}
                        >
                          Bind
                        </button>
                      </div>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <p className="whatsapp-directory-boundary">
        Mapping here reuses the existing Talent <code>wa_identity</code>. PMO operator WhatsApp identity remains a separate authorization boundary. Selecting a closing group does not send anything; scheduled/group delivery is enabled only in later Payroll delivery cards.
      </p>
    </section>
  );
}
