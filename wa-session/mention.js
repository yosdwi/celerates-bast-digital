"use strict";

// Mention detection, split out from server.js so it's testable without a
// live Baileys socket (see mention.test.js).

const { jidDecode } = require("@whiskeysockets/baileys");

const TRIGGER = /^\s*[@!/]?\s*bast\s*bot\b|^\s*!bast\b|^\s*@\s*conform\b/i;

function ownUserIds(sock) {
  const ids = new Set();
  const candidates = [
    sock?.user?.id,
    sock?.user?.lid,
    sock?.authState?.creds?.me?.id,
    sock?.authState?.creds?.me?.lid,
  ];
  for (const raw of candidates) {
    const decoded = raw && jidDecode(raw);
    if (decoded?.user) ids.add(decoded.user);
  }
  return ids;
}

function contextInfoOf(message) {
  const content = message.message || {};
  return (
    content.extendedTextMessage?.contextInfo ||
    content.imageMessage?.contextInfo ||
    content.videoMessage?.contextInfo ||
    content.documentMessage?.contextInfo ||
    null
  );
}

function isForUs(message, text, ownIds) {
  const mentioned = contextInfoOf(message)?.mentionedJid || [];
  const mentionsUs = mentioned.some((jid) => {
    const decoded = jidDecode(jid);
    return !!decoded?.user && ownIds.has(decoded.user);
  });
  return mentionsUs || TRIGGER.test(text);
}

// Transport hint only; Python remains the business-intent authority.
const BUSINESS_WORDS =
  /\b(restart|reboot|matikan|hidupkan|nyalakan|shutdown|kill|export|absen|generate|buat bast|bikin bast|evidence|status|cek|detail|kenapa|docker|system status|status sistem|status docker|status server)\b/i;
const CONVERSATION_WORDS =
  /\b(kenalin|kenalan|siapa kamu|siapa nih|siapa sih|kamu siapa|halo|hai conform|hallo|hi conform|assalamualaikum|pagi conform|siang conform|sore conform|malam conform|makasih|terima kasih|thanks|thank you|mantap|keren|bisa ngapain|bisa apa aja|bantuin apa|fungsi kamu|tolong apa)\b/i;

function looksLikeConversation(text) {
  const stripped = text.replace(/@[\w.-]+/g, " ");
  return !BUSINESS_WORDS.test(stripped) && CONVERSATION_WORDS.test(stripped);
}

const DM_FAST_PATH_WORDS =
  /\b(attendance|absen|absensi|tasklist|task list|kurang|progress|evidence|rebind|ganti nomor|cuti|izin|ijin|sakit)\b/i;
const DM_NAVIGATION = /^(menu|home|kembali|bantuan|help|batal|cancel)$/i;
const DM_CONFIRMATION = /^(ya|iya|yes|y|betul|benar|yoi|bener|bukan|tidak|no|salah|nggak|gak|ga)$/i;
const DM_CLOCK = /^(?:[01]?\d|2[0-3])[:.]\d{2}(?:\s+(?:[01]?\d|2[0-3])[:.]\d{2})?$/;

function looksLikeDmFastPath(text) {
  const stripped = text.replace(/@[\w.-]+/g, " ").trim();
  if (!stripped) return true;
  if (/^\d+$/.test(stripped)) return true;
  if (/^(pmo:|rebind:)/i.test(stripped)) return true;
  if (/^PMO-[A-Za-z0-9_-]+$/.test(stripped)) return true;
  if (DM_NAVIGATION.test(stripped)) return true;
  if (DM_CONFIRMATION.test(stripped)) return true;
  if (DM_CLOCK.test(stripped)) return true;
  if (looksLikeConversation(stripped)) return true;
  return DM_FAST_PATH_WORDS.test(stripped);
}

module.exports = {
  TRIGGER,
  ownUserIds,
  isForUs,
  looksLikeConversation,
  looksLikeDmFastPath,
  contextInfoOf,
};
