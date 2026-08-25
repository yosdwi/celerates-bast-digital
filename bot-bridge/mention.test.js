"use strict";

// Focused regression coverage for the real @mention bug: WhatsApp mentions a
// group participant using either the phone-number JID or the privacy "@lid"
// JID depending on the group's addressing mode, and a bot's LID shares no
// digits with its phone number. Fixture values below are the bot's own real
// id/lid pair as Baileys wrote them to bot-bridge/auth/creds.json.

const test = require("node:test");
const assert = require("node:assert/strict");
const { ownUserIds, isForUs, looksLikeConversation, looksLikeDmFastPath } = require("./mention");

const SOCK = {
  user: { id: "62881080735871:1@s.whatsapp.net", lid: "250758209531984:1@lid", name: "conform" },
};

function textMessage(text, mentionedJid) {
  return {
    message: {
      extendedTextMessage: {
        text,
        contextInfo: mentionedJid ? { mentionedJid } : undefined,
      },
    },
  };
}

test("real @mention via LID JID is accepted", () => {
  const message = textMessage("liat status bast dong bulan agustus ini", [
    "250758209531984@lid",
  ]);
  assert.equal(isForUs(message, "liat status bast dong bulan agustus ini", ownUserIds(SOCK)), true);
});

test("real @mention via phone-number JID is accepted (non-LID-mode group)", () => {
  const message = textMessage("status bast agustus", ["62881080735871@s.whatsapp.net"]);
  assert.equal(isForUs(message, "status bast agustus", ownUserIds(SOCK)), true);
});

test("literal '@conform' text still triggers without mention metadata", () => {
  const message = textMessage("@conform status bast agustus");
  assert.equal(isForUs(message, "@conform status bast agustus", ownUserIds(SOCK)), true);
});

test("group message with no mention and no trigger word is ignored", () => {
  const message = textMessage("ada yang tau meeting jam berapa?");
  assert.equal(isForUs(message, "ada yang tau meeting jam berapa?", ownUserIds(SOCK)), false);
});

test("mentioning someone else does not trigger the bot", () => {
  const message = textMessage("gimana progress kamu?", ["6281234567890@s.whatsapp.net"]);
  assert.equal(isForUs(message, "gimana progress kamu?", ownUserIds(SOCK)), false);
});

test("real @mention on a photo caption is accepted (contextInfo lives on imageMessage, not extendedTextMessage)", () => {
  const message = {
    message: {
      imageMessage: {
        caption: "evidence-nya nih",
        contextInfo: { mentionedJid: ["250758209531984@lid"] },
      },
    },
  };
  assert.equal(isForUs(message, "evidence-nya nih", ownUserIds(SOCK)), true);
});

test("photo sent with no caption and no mention is not for us", () => {
  const message = { message: { imageMessage: {} } };
  assert.equal(isForUs(message, "", ownUserIds(SOCK)), false);
});

test("bot display-name change does not affect mention detection", () => {
  const renamed = { user: { ...SOCK.user, name: "BAST Bot v2" } };
  const message = textMessage("status bast", ["250758209531984@lid"]);
  assert.equal(isForUs(message, "status bast", ownUserIds(renamed)), true);
});

test("a greeting is recognized as conversation (skip the wait notice)", () => {
  assert.equal(looksLikeConversation("@conform kenalin dong siapa nih"), true);
  assert.equal(looksLikeConversation("@conform makasih ya"), true);
});

test("business commands are never treated as conversation, even if casual", () => {
  assert.equal(looksLikeConversation("@conform status bast agustus dong"), false);
  assert.equal(looksLikeConversation("@conform generate bast developer"), false);
  assert.equal(looksLikeConversation("@conform export attendance shifting"), false);
  assert.equal(looksLikeConversation("@conform restart postgres dong"), false);
});

test("DM keyword fast paths skip the wait notice", () => {
  assert.equal(looksLikeDmFastPath("tasklist aku bulan ini"), true);
  assert.equal(looksLikeDmFastPath("attendance"), true);
  assert.equal(looksLikeDmFastPath("evidence yang kurang apa"), true);
  assert.equal(looksLikeDmFastPath("1"), true);
  assert.equal(looksLikeDmFastPath(""), true);
});

test("DM free-form questions get the wait notice (LLM fallback)", () => {
  assert.equal(looksLikeDmFastPath("yang belum closed apa aja"), false);
  assert.equal(looksLikeDmFastPath("clock in aku yang belum lengkap yang mana"), false);
});
