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

module.exports = { TRIGGER, ownUserIds, isForUs };
