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

function isForUs(message, text, ownIds) {
  const mentioned = message.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
  const mentionsUs = mentioned.some((jid) => {
    const decoded = jidDecode(jid);
    return !!decoded?.user && ownIds.has(decoded.user);
  });
  return mentionsUs || TRIGGER.test(text);
}

// Keep in sync with src/digital_bast/bot/whatsapp.py's _INTENT_RULES /
// _CONVERSATION_WORDS. This is a client-side proxy only, used to decide
// whether the "Siap, tunggu ..." heads-up is worth sending before the CLI
// even runs -- cli.py::_group_reply is the actual authority on intent (a
// business keyword there always wins over a conversation one), this just
// needs to avoid a false "conversation" skip when a business word is also
// present, so it stays conservative: any business-ish word forces the wait.
const BUSINESS_WORDS =
  /\b(restart|reboot|matikan|hidupkan|nyalakan|shutdown|kill|export|absen|generate|buat bast|bikin bast|evidence|status|cek|detail|kenapa|docker|system status|status sistem|status docker|status server)\b/i;
const CONVERSATION_WORDS =
  /\b(kenalin|kenalan|siapa kamu|siapa nih|siapa sih|kamu siapa|halo|hai conform|hallo|hi conform|assalamualaikum|pagi conform|siang conform|sore conform|malam conform|makasih|terima kasih|thanks|thank you|mantap|keren|bisa ngapain|bisa apa aja|bantuin apa|fungsi kamu|tolong apa)\b/i;

function looksLikeConversation(text) {
  const stripped = text.replace(/@[\w.-]+/g, " ");
  return !BUSINESS_WORDS.test(stripped) && CONVERSATION_WORDS.test(stripped);
}

module.exports = { TRIGGER, ownUserIds, isForUs, looksLikeConversation };
