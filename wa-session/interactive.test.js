"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  messageText,
  parseInteractiveReply,
  fallbackText,
  sendInteractiveReply,
} = require("./interactive");

const PAYLOAD = {
  text: "Halo Yoses 👋",
  footer: "Digital BAST",
  actions: [
    { id: "status", label: "Status Saya" },
    { id: "attendance", label: "Attendance" },
    { id: "tasklist", label: "Task & Evidence" },
  ],
};

// A real incoming message always carries a populated `.message` -- Baileys'
// own generateWAMessageFromContent dereferences `quoted.message` while
// threading the reply, so a bare `{ key: {} }` stub (no `.message`) throws
// inside that real, unmocked call and would misleadingly look like our own
// code failing instead of an unrealistic test fixture.
const INCOMING_MESSAGE = {
  key: { remoteJid: "628123@s.whatsapp.net", fromMe: false, id: "ABCD1234" },
  message: { conversation: "halo" },
};

test("messageText reads taps from every known reply shape", () => {
  assert.equal(
    messageText({ message: { buttonsResponseMessage: { selectedButtonId: "status" } } }),
    "status",
  );
  assert.equal(
    messageText({ message: { templateButtonReplyMessage: { selectedId: "attendance" } } }),
    "attendance",
  );
  assert.equal(
    messageText({
      message: { listResponseMessage: { singleSelectReply: { selectedRowId: "tasklist" } } },
    }),
    "tasklist",
  );
  assert.equal(
    messageText({
      message: {
        interactiveResponseMessage: {
          nativeFlowResponseMessage: { paramsJson: JSON.stringify({ id: "status" }) },
        },
      },
    }),
    "status",
  );
  assert.equal(messageText({ message: { conversation: "halo" } }), "halo");
});

test("parseInteractiveReply accepts a well-formed interactive payload", () => {
  const parsed = parseInteractiveReply(JSON.stringify({ kind: "interactive", ...PAYLOAD }));
  assert.deepEqual(parsed, PAYLOAD);
});

test("parseInteractiveReply rejects anything that isn't kind:interactive", () => {
  assert.equal(parseInteractiveReply("plain text"), null);
  assert.equal(parseInteractiveReply(JSON.stringify({ kind: "file", path: "/x" })), null);
  assert.equal(parseInteractiveReply(JSON.stringify({ kind: "interactive" })), null);
});

test("fallbackText lists every action so it stays usable without tappable buttons", () => {
  const text = fallbackText(PAYLOAD);
  assert.match(text, /Status Saya: status/);
  assert.match(text, /Attendance: attendance/);
  assert.match(text, /Task & Evidence: tasklist/);
});

// Native-flow sending is disabled (see the comment above sendInteractiveReply
// in interactive.js): three live tests all showed relayMessage() resolving
// with no error while the message never reached the recipient at all, which
// meant real talent replies with buttons were being silently dropped in
// production. sendInteractiveReply now always uses the plain-text fallback,
// which every one of those same live tests confirmed actually delivers.
test("sendInteractiveReply always sends the text fallback (native-flow is disabled)", async () => {
  const sent = [];
  const relayCalls = [];
  const sock = {
    user: { id: "62881080735871:2@s.whatsapp.net" },
    relayMessage: async (jid, message, options) => {
      relayCalls.push({ jid, message, options });
    },
    sendMessage: async (jid, content, options) => {
      sent.push({ jid, content, options });
    },
  };

  await sendInteractiveReply(sock, "628123@s.whatsapp.net", INCOMING_MESSAGE, PAYLOAD);

  assert.equal(relayCalls.length, 0);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].jid, "628123@s.whatsapp.net");
  assert.match(sent[0].content.text, /Pilihan:/);
  assert.match(sent[0].content.text, /Status Saya: status/);
  assert.deepEqual(sent[0].options, { quoted: INCOMING_MESSAGE });
});
