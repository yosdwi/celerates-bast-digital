"use strict";

// Personalizes the "give me a sec" heads-up server.js sends before handing
// the message off to the CLI (see server.js::handleGroupMessage). Deliberately
// template-only, no LLM call -- that heads-up exists specifically to land
// *instantly*, before the 10-15s CLI/LLM round trip even starts, so routing
// it through an LLM would delay the one message meant to arrive immediately.

// WhatsApp's pushName is often a full name ("Putri Wulandari") or a name with
// emoji/decoration ("~ Putri 🌸") -- only the first bare word reads naturally
// after "kak" in a chat greeting.
function firstName(pushName) {
  if (!pushName) return null;
  const match = pushName.trim().match(/[\p{L}\p{N}]+/u);
  return match ? match[0] : null;
}

const WITH_NAME = [
  (name) => `Siap kak ${name}, tunggu sebentar ya aku proses dulu 🙏`,
  (name) => `Oke kak ${name}, bentar ya lagi aku cek 🔎`,
  (name) => `Baik kak ${name}, ditunggu sebentar ya aku kerjain dulu`,
  (name) => `Noted kak ${name}, proses dulu ya sebentar`,
  (name) => `Siap kak ${name}, aku cek dulu ya sebentar 🙏`,
];

const WITHOUT_NAME = [
  "Siap, tunggu sebentar ya aku proses dulu 🙏",
  "Oke, bentar ya lagi aku cek 🔎",
  "Baik, ditunggu sebentar ya aku kerjain dulu",
  "Noted, proses dulu ya sebentar",
];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function waitingReply(pushName) {
  const name = firstName(pushName);
  return name ? pick(WITH_NAME)(name) : pick(WITHOUT_NAME);
}

module.exports = { firstName, waitingReply };
