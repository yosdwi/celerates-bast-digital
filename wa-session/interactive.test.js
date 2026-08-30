"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  messageText,
  parseInteractiveReply,
  fallbackText,
  forgetMenu,
  rememberMenu,
  resolveDigitReply,
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
  digitShortcuts: true,
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

test("parseInteractiveReply defaults digitShortcuts to true, honors an explicit false", () => {
  const defaulted = parseInteractiveReply(
    JSON.stringify({ kind: "interactive", text: "Halo", actions: [] }),
  );
  assert.equal(defaulted.digitShortcuts, true);

  const disabled = parseInteractiveReply(
    JSON.stringify({ kind: "interactive", text: "Halo", actions: [], digitShortcuts: false }),
  );
  assert.equal(disabled.digitShortcuts, false);
});

test("fallbackText numbers every action so replying is a digit, not a tap", () => {
  const text = fallbackText(PAYLOAD);
  assert.match(text, /1\. Status Saya/);
  assert.match(text, /2\. Attendance/);
  assert.match(text, /3\. Task & Evidence/);
  assert.match(text, /Balas dengan angka/);
  // The raw action id (e.g. a PMO approve/reject id with an embedded uuid)
  // must never be shown to the user -- resolveDigitReply is how it gets used.
  assert.doesNotMatch(text, /: status/);
});

test("fallbackText falls back to the old label:id form when digitShortcuts is disabled", () => {
  // e.g. dm_workflow._attendance_status_reply's own evidence-candidate list
  // already uses bare numbers for something else -- digits here would be
  // ambiguous, so keep this one screen's pre-existing typed-keyword form.
  const text = fallbackText({ ...PAYLOAD, digitShortcuts: false });
  assert.doesNotMatch(text, /^1\. /m);
  assert.match(text, /Status Saya: status/);
  assert.match(text, /Attendance: attendance/);
  assert.match(text, /Task & Evidence: tasklist/);
});

test("rememberMenu + resolveDigitReply turns a typed number back into the real action id", () => {
  const jid = "6281111111111@s.whatsapp.net";
  rememberMenu(jid, PAYLOAD.actions);
  assert.equal(resolveDigitReply(jid, "1"), "status");
  assert.equal(resolveDigitReply(jid, "2"), "attendance");
  assert.equal(resolveDigitReply(jid, " 3 "), "tasklist");
});

test("resolveDigitReply leaves text alone when there's no menu, it's out of range, or not a digit", () => {
  const withMenu = "6282222222222@s.whatsapp.net";
  const withoutMenu = "6283333333333@s.whatsapp.net";
  rememberMenu(withMenu, PAYLOAD.actions);

  assert.equal(resolveDigitReply(withoutMenu, "1"), "1");
  assert.equal(resolveDigitReply(withMenu, "99"), "99");
  assert.equal(resolveDigitReply(withMenu, "status"), "status");
  assert.equal(resolveDigitReply(withMenu, "1 dong"), "1 dong");
});

test("forgetMenu stops a stale menu from swallowing an unrelated bare-number reply", () => {
  // Mirrors production: e.g. the CLI's own numbered evidence-candidate list
  // is plain text, not an interactive() payload, so the digit it expects
  // back must reach it untouched instead of being resolved against an
  // older menu that's no longer on screen.
  const jid = "6284444444444@s.whatsapp.net";
  rememberMenu(jid, PAYLOAD.actions);
  forgetMenu(jid);
  assert.equal(resolveDigitReply(jid, "1"), "1");
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
  assert.match(sent[0].content.text, /1\. Status Saya/);
  assert.deepEqual(sent[0].options, { quoted: INCOMING_MESSAGE });
});
