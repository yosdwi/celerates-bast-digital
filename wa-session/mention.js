"use strict";

// Mention detection, split out from server.js so it's testable without a
// live Baileys socket (see mention.test.js).
//
// WhatsApp mentions a group participant by one JID form, but which form
// (phone-number "@s.whatsapp.net" vs privacy-preserving "@lid") depends on
// the group's addressing mode and is unrelated to the other -- a bot's LID
// user id shares no digits with its phone number. So "are we mentioned" must
// compare the *decoded user id* against every JID form we actually have for
// ourselves, not do a string prefix match against only the phone-number JID.

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

// contextInfo (which carries mentionedJid) lives on whichever message type
// is actually present -- a photo/document sent with a tap-to-mention tag
// carries it on imageMessage/documentMessage, not extendedTextMessage.
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

// Keep in sync with src/digital_bast/bot/whatsapp.py's _INTENT_RULES /
// _CONVERSATION_WORDS. This is a transport-side hint only. The worker/CLI is
// the authority on business intent; wa-session uses this hint only to avoid
// showing a wait acknowledgement for obviously instant conversation paths.
const BUSINESS_WORDS =
  /\b(restart|reboot|matikan|hidupkan|nyalakan|shutdown|kill|export|absen|generate|buat bast|bikin bast|evidence|status|cek|detail|kenapa|docker|system status|status sistem|status docker|status server)\b/i;
const CONVERSATION_WORDS =
  /\b(kenalin|kenalan|siapa kamu|siapa nih|siapa sih|kamu siapa|halo|hai conform|hallo|hi conform|assalamualaikum|pagi conform|siang conform|sore conform|malam conform|makasih|terima kasih|thanks|thank you|mantap|keren|bisa ngapain|bisa apa aja|bantuin apa|fungsi kamu|tolong apa)\b/i;

function looksLikeConversation(text) {
  const stripped = text.replace(/@[\w.-]+/g, " ");
  return !BUSINESS_WORDS.test(stripped) && CONVERSATION_WORDS.test(stripped);
}

// Keep in sync with src/digital_bast/cli.py's deterministic DM paths. This
// does not decide intent; it only marks messages where a pre-emptive wait
// notice would be bad UX. Slow non-deterministic paths are additionally
// protected by server.js's delayed-notice timer, so they only acknowledge
// waiting after real latency has occurred.
const DM_FAST_PATH_WORDS =
  /\b(attendance|absen|absensi|tasklist|task list|kurang|progress|evidence)\b/i;
const DM_NAVIGATION = /^(menu|home|kembali|bantuan|help)$/i;

function looksLikeDmFastPath(text) {
  const stripped = text.replace(/@[\w.-]+/g, " ").trim();
  if (!stripped) return true;
  if (/^\d+$/.test(stripped)) return true;
  if (DM_NAVIGATION.test(stripped)) return true;
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
