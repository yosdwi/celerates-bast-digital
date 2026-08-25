import { useEffect, useMemo, useState } from "react";
import { getFollowUpDraft, sendFollowUp } from "../api/talentops";
import type { FollowUpDraft, FollowUpSendResponse, FollowUpSource, PeriodView, TalentOpsSession } from "../api/types";
import { CloseIcon, RefreshIcon, SparkleIcon } from "./Icons";

interface Props {
  session: TalentOpsSession;
  nrp: string;
  name: string;
  period: Pick<PeriodView, "year" | "month" | "label">;
  onClose: () => void;
  onSent?: () => void;
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

function resultMessage(result: FollowUpSendResponse): string {
  switch (result.status) {
    case "sent":
      return result.duplicate ? "Message was already sent; duplicate send prevented." : "WhatsApp follow-up sent.";
    case "not_bound":
      return "This talent has not connected their WhatsApp identity yet.";
    case "bridge_unavailable":
      return "WhatsApp bridge is unavailable. Nothing was sent.";
    case "no_blockers":
      return "Current readiness has no blocker anymore. Nothing was sent.";
    default:
      return "The message could not be sent. Nothing was marked as delivered.";
  }
}

export default function FollowUpComposer({ session, nrp, name, period, onClose, onSent }: Props) {
  const [draft, setDraft] = useState<FollowUpDraft | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FollowUpSendResponse | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());

  const source: FollowUpSource = useMemo(() => {
    if (!draft) return "deterministic";
    return message.trim() === draft.message.trim() ? draft.source : "edited";
  }, [draft, message]);

  async function loadDraft() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const next = await getFollowUpDraft(session.csrf_token, nrp, period);
      setDraft(next);
      setMessage(next.message);
      setIdempotencyKey(newIdempotencyKey());
    } catch {
      setError("Follow-up draft is unavailable. Try again after checking the TalentOps API and Ollama/bridge configuration.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDraft();
    // A new composer instance owns one initial load. Regeneration is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nrp, period.year, period.month]);

  async function send() {
    if (!draft || sending || !message.trim() || !draft.whatsapp_bound) return;
    setSending(true);
    setError(null);
    setResult(null);
    try {
      const next = await sendFollowUp(
        session.csrf_token,
        nrp,
        period,
        message.trim(),
        source,
        idempotencyKey,
      );
      setResult(next);
      if (next.status === "sent") onSent?.();
      if (next.status !== "sent") setIdempotencyKey(newIdempotencyKey());
    } catch {
      // Keep the same idempotency key: the request may have reached the server
      // before the browser lost the response, so retry must remain safe.
      setError("Delivery status is unknown because the request failed. Retry uses the same idempotency key to prevent duplicate messages.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="followup-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="followup-panel" role="dialog" aria-modal="true" aria-label={`Follow up ${name}`}>
        <div className="followup-head">
          <div><span>TalentOps action</span><h2>Follow up {name}</h2><p>{nrp} · {period.label}</p></div>
          <button type="button" className="icon-button" aria-label="Close follow-up" onClick={onClose}><CloseIcon /></button>
        </div>

        {loading ? <div className="followup-loading">Preparing current blockers and draft…</div> : null}
        {error ? <div className="followup-error">{error}</div> : null}

        {draft ? (
          <div className="followup-body">
            <div className="followup-channel-row">
              <div><span>Channel</span><strong>WhatsApp DM</strong></div>
              <span className={`followup-channel-status ${draft.whatsapp_bound ? "connected" : "unbound"}`}>
                {draft.whatsapp_bound ? "Connected" : "Not connected"}
              </span>
            </div>

            {draft.last_follow_up ? (
              <div className="followup-history">
                <span>Last follow-up</span>
                <strong>{draft.last_follow_up.status}</strong>
                <small>{new Date(draft.last_follow_up.sent_at ?? draft.last_follow_up.created_at).toLocaleString()} · {draft.last_follow_up.created_by}</small>
              </div>
            ) : null}

            <label htmlFor="followup-message">Message</label>
            <textarea
              id="followup-message"
              rows={8}
              maxLength={4000}
              value={message}
              onChange={(event) => { setMessage(event.target.value); setResult(null); }}
            />
            <div className="followup-message-meta">
              <span>{draft.source === "ai" ? "AI-assisted draft · grounded in current talent facts" : "Deterministic fallback draft"}</span>
              <span>{message.length}/4000</span>
            </div>

            <button type="button" className="secondary-button followup-regenerate" onClick={() => void loadDraft()} disabled={loading || sending}>
              {draft.source === "ai" ? <SparkleIcon /> : <RefreshIcon />}Regenerate draft
            </button>

            {!draft.whatsapp_bound ? (
              <div className="followup-warning">WhatsApp send is disabled until this talent completes the existing NRP-to-WhatsApp binding flow.</div>
            ) : null}
            {result ? <div className={`followup-result ${result.status}`}>{resultMessage(result)}</div> : null}
          </div>
        ) : null}

        <div className="followup-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="primary-button"
            disabled={!draft?.whatsapp_bound || !message.trim() || sending || loading || result?.status === "sent"}
            onClick={() => void send()}
          >
            {sending ? "Sending…" : result?.status === "sent" ? "Sent" : "Send WhatsApp"}
          </button>
        </div>
      </section>
    </div>
  );
}
