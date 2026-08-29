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

test("sendInteractiveReply relays a native-flow message and never falls back on success", async () => {
  const relayed = [];
  const sock = {
    user: { id: "62881080735871:2@s.whatsapp.net" },
    relayMessage: async (jid, message, options) => {
      relayed.push({ jid, message, options });
    },
    sendMessage: async () => {
      throw new Error("fallback should not be used when relayMessage succeeds");
    },
  };

  await sendInteractiveReply(sock, "628123@s.whatsapp.net", INCOMING_MESSAGE, PAYLOAD);

  assert.equal(relayed.length, 1);
  const { jid, message } = relayed[0];
  assert.equal(jid, "628123@s.whatsapp.net");
  const nativeFlow = message.interactiveMessage.nativeFlowMessage;
  assert.equal(nativeFlow.buttons.length, 3);
  assert.deepEqual(JSON.parse(nativeFlow.buttons[0].buttonParamsJson), {
    display_text: "Status Saya",
    id: "status",
  });
  assert.equal(nativeFlow.messageVersion, 1);
  // Insurance against WhatsApp silently not rendering the buttons at all.
  assert.match(message.interactiveMessage.body.text, /Atau ketik: Status Saya, Attendance/);
});

test("sendInteractiveReply falls back to plain text if the native-flow send throws", async () => {
  const sent = [];
  const sock = {
    user: { id: "62881080735871:2@s.whatsapp.net" },
    relayMessage: async () => {
      throw new Error("WhatsApp rejected it");
    },
    sendMessage: async (jid, content) => {
      sent.push({ jid, content });
    },
  };
  const logs = [];

  await sendInteractiveReply(
    sock,
    "628123@s.whatsapp.net",
    INCOMING_MESSAGE,
    PAYLOAD,
    (line) => logs.push(line),
  );

  assert.equal(sent.length, 1);
  assert.match(sent[0].content.text, /Pilihan:/);
  assert.equal(logs.some((line) => line.includes("text fallback")), true);
});
