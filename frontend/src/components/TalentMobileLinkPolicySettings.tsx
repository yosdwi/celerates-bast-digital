import { useEffect, useState } from "react";
import {
  getTalentMobileLinkPolicy,
  saveTalentMobileLinkPolicy,
} from "../api/talent-mobile-policy";
import type { TalentOpsSession } from "../api/types";

interface Props {
  session: TalentOpsSession;
}

function isAdmin(session: TalentOpsSession): boolean {
  return ["owner", "admin"].includes(session.user.role.toLowerCase());
}

export default function TalentMobileLinkPolicySettings({ session }: Props) {
  const admin = isAdmin(session);
  const [ttlDays, setTtlDays] = useState(7);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!admin) return;
    let active = true;
    void getTalentMobileLinkPolicy()
      .then((policy) => {
        if (!active) return;
        setTtlDays(policy.ttl_days);
        setLoaded(true);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Talent URL policy unavailable.");
      });
    return () => {
      active = false;
    };
  }, [admin]);

  if (!admin) return null;

  async function save() {
    if (busy || !loaded) return;
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      const policy = await saveTalentMobileLinkPolicy(session.csrf_token, ttlDays);
      setTtlDays(policy.ttl_days);
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Talent URL policy update failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel settings-card">
      <div className="panel-title-row">
        <div>
          <h2>Talent URL validity</h2>
          <span>Validity for manual Talent URLs issued from PMO Web</span>
        </div>
        <button className="primary-button" type="button" disabled={busy || !loaded} onClick={() => void save()}>
          {busy ? "Saving…" : "Save validity"}
        </button>
      </div>

      <div className="workflow-form-grid">
        <label>
          Link validity
          <select value={ttlDays} disabled={!loaded || busy} onChange={(event) => { setTtlDays(Number(event.target.value)); setSaved(false); }}>
            <option value={1}>1 day</option>
            <option value={2}>2 days</option>
            <option value={3}>3 days</option>
            <option value={4}>4 days</option>
            <option value={5}>5 days</option>
            <option value={6}>6 days</option>
            <option value={7}>7 days</option>
          </select>
        </label>
      </div>

      <p>
        Applies only to new manual URLs generated in Talents → Talent URLs. Existing URLs keep
        the expiry embedded when they were created. WhatsApp-generated Talent links remain
        short-lived at 30 minutes.
      </p>
      {saved ? <div className="settings-status">Saved · new PMO Talent URLs are valid for {ttlDays} day{ttlDays === 1 ? "" : "s"}</div> : null}
      {error ? <div className="ai-unavailable" role="alert">{error}</div> : null}
    </section>
  );
}
