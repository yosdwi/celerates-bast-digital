"use strict";

// Ported from whatsmeow-session/helpers.go and bridge.go so the prototype
// exercises the same trigger/menu/envelope behavior the real bridge relies
// on, not just bare send/receive. See docs/wa-session-whatsapp-web-js-migration-plan.md.

const crypto = require("node:crypto");

const MAX_MESSAGE_CHARS = 4000;
const MAX_REQUEST_ID_CHARS = 128;
const MAX_COMPLETED_SENDS = 1024;
const PENDING_MENU_TTL_MS = 15 * 60 * 1000;
const MAX_PENDING_MENUS = 512;

// Case-insensitive: "bast bot" / "!bast" / "@conform" at the start of the
// (mention-stripped) message. Mirrors whatsmeow-session/bridge.go's groupTrigger.
const GROUP_TRIGGER = /^\s*[@!/]?\s*bast\s*bot\b|^\s*!bast\b|^\s*@\s*conform\b/i;

const BUSINESS_WORDS =
  /\b(restart|reboot|matikan|hidupkan|nyalakan|shutdown|kill|export|absen|generate|buat bast|bikin bast|evidence|status|cek|detail|kenapa|docker|system status|status sistem|status docker|status server)\b/i;
const CONVERSATION_WORDS =
  /\b(kenalin|kenalan|siapa kamu|siapa nih|siapa sih|kamu siapa|halo|hai conform|hallo|hi conform|assalamualaikum|pagi conform|siang conform|sore conform|malam conform|makasih|terima kasih|thanks|thank you|mantap|keren|bisa ngapain|bisa apa aja|bantuin apa|fungsi kamu|tolong apa)\b/i;
const DM_FAST_WORDS =
  /\b(attendance|absen|absensi|tasklist|task list|kurang|progress|evidence|rebind|ganti nomor|cuti|izin|ijin|sakit)\b/i;
const DM_NAVIGATION = /^(menu|home|kembali|bantuan|help|batal|cancel)$/i;
const DM_CONFIRMATION = /^(ya|iya|yes|y|betul|benar|yoi|bener|bukan|tidak|no|salah|nggak|gak|ga)$/i;
const DM_CLOCK = /^(?:[01]?\d|2[0-3])[:.]\d{2}(?:\s+(?:[01]?\d|2[0-3])[:.]\d{2})?$/;
const MENTION_STRIP = /@[\w.-]+/g;
const DIGITS_ONLY = /^[0-9]+$/;

function looksLikeConversation(text) {
  const stripped = text.replace(MENTION_STRIP, " ");
  return !BUSINESS_WORDS.test(stripped) && CONVERSATION_WORDS.test(stripped);
}

function looksLikeDMFastPath(text) {
  const stripped = text.replace(MENTION_STRIP, " ").trim();
  if (
    stripped === "" ||
    /^\d+$/.test(stripped) ||
    /^(pmo:|rebind:)/i.test(stripped) ||
    /^PMO-[A-Za-z0-9_-]+$/.test(stripped) ||
    DM_NAVIGATION.test(stripped) ||
    DM_CONFIRMATION.test(stripped) ||
    DM_CLOCK.test(stripped) ||
    looksLikeConversation(stripped)
  ) {
    return true;
  }
  return DM_FAST_WORDS.test(stripped);
}

function firstName(pushName) {
  const match = String(pushName || "")
    .trim()
    .match(/[\p{L}\p{N}]+/u);
  return match ? match[0] : "";
}

function waitingReply(pushName) {
  const name = firstName(pushName);
  if (name) return `Siap kak ${name}, tunggu sebentar ya aku proses dulu \u{1F64F}`;
  return "Siap, tunggu sebentar ya aku proses dulu \u{1F64F}";
}

function friendlyError(logf, contextName, detail) {
  const ref = crypto.randomBytes(6).toString("hex");
  logf(`${contextName} failed [${ref}]: ${detail}`);
  return `Maaf, proses gagal saat ${contextName}.\nCoba lagi beberapa saat atau hubungi admin jika tetap gagal. (ref: ${ref})`;
}

// { kind: "interactive", text, footer?, actions: [{id,label}], digitShortcuts? }
function parseInteractiveReply(text) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  if (!payload || payload.kind !== "interactive" || !payload.text) return null;
  const actions = Array.isArray(payload.actions) ? payload.actions : [];
  const filtered = actions
    .map((a) => ({ id: String(a?.id ?? "").trim(), label: String(a?.label ?? "").trim() }))
    .filter((a) => a.id && a.label);
  return {
    text: payload.text,
    footer: payload.footer || "Digital BAST",
    actions: filtered,
    digitShortcuts: payload.digitShortcuts === undefined ? true : Boolean(payload.digitShortcuts),
  };
}

function fallbackText(payload) {
  const lines = [payload.text];
  if (payload.actions.length > 0) {
    lines.push("");
    if (payload.digitShortcuts) {
      payload.actions.forEach((a, i) => lines.push(`${i + 1}. ${a.label}`));
    } else {
      payload.actions.forEach((a) => lines.push(`• ${a.label}: ${a.id}`));
    }
  }
  if (payload.footer) lines.push("", `_${payload.footer}_`);
  return lines.join("\n");
}

// { kind: "file", path, filename?, caption? }
function parseFileReply(text) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }
  if (!payload || payload.kind !== "file" || !String(payload.path || "").trim()) return null;
  return payload;
}

class MenuStore {
  constructor() {
    this.items = new Map(); // jid -> { actions, expiresAt }
  }

  remember(jid, actions) {
    this.items.set(jid, { actions: [...actions], expiresAt: Date.now() + PENDING_MENU_TTL_MS });
    if (this.items.size <= MAX_PENDING_MENUS) return;
    let oldestKey = null;
    let oldest = Infinity;
    for (const [key, entry] of this.items) {
      if (entry.expiresAt < oldest) {
        oldest = entry.expiresAt;
        oldestKey = key;
      }
    }
    if (oldestKey !== null) this.items.delete(oldestKey);
  }

  forget(jid) {
    this.items.delete(jid);
  }

  resolve(jid, text) {
    const trimmed = text.trim();
    if (!DIGITS_ONLY.test(trimmed)) return text;
    const entry = this.items.get(jid);
    if (!entry || Date.now() > entry.expiresAt) {
      if (entry) this.items.delete(jid);
      return text;
    }
    const n = Number(trimmed);
    if (!Number.isInteger(n) || n < 1 || n > entry.actions.length) return text;
    return entry.actions[n - 1].id;
  }
}

// Same idempotency contract as whatsmeow-session's outboundStore: a
// request_id retried with the same {jid,text} replays the cached result; a
// retried request_id with different {jid,text} is a conflict.
class OutboundDedupeStore {
  constructor() {
    this.inFlight = new Map();
    this.completed = new Map();
    this.order = [];
  }

  async run(requestId, jid, text, sendFn) {
    const done = this.completed.get(requestId);
    if (done) {
      if (done.jid !== jid || done.text !== text) return { conflict: true };
      return done.result;
    }
    const pending = this.inFlight.get(requestId);
    if (pending) {
      if (pending.jid !== jid || pending.text !== text) return { conflict: true };
      return pending.promise;
    }
    const promise = (async () => {
      const result = await sendFn();
      this.inFlight.delete(requestId);
      if (result.status === "sent") {
        this.completed.set(requestId, { jid, text, result });
        this.order.push(requestId);
        if (this.order.length > MAX_COMPLETED_SENDS) {
          const oldest = this.order.shift();
          this.completed.delete(oldest);
        }
      }
      return result;
    })();
    this.inFlight.set(requestId, { jid, text, promise });
    return promise;
  }
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (a.length === 0 || a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

module.exports = {
  MAX_MESSAGE_CHARS,
  MAX_REQUEST_ID_CHARS,
  GROUP_TRIGGER,
  looksLikeConversation,
  looksLikeDMFastPath,
  waitingReply,
  friendlyError,
  parseInteractiveReply,
  fallbackText,
  parseFileReply,
  MenuStore,
  OutboundDedupeStore,
  safeEqual,
};
