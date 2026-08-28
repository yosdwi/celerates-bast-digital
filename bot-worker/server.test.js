"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { safeEqual, cliArgsFor } = require("./server");

test("safeEqual only accepts equal non-empty tokens", () => {
  assert.equal(safeEqual("secret-value", "secret-value"), true);
  assert.equal(safeEqual("secret-value", "other-value"), false);
  assert.equal(safeEqual("", ""), false);
  assert.equal(safeEqual(undefined, "secret-value"), false);
});

test("cliArgsFor maps a text reply without a jid/channel", () => {
  assert.deepEqual(cliArgsFor({ kind: "text", text: "status 1 sampai 31 Agustus" }), [
    "bot-reply",
    "--text",
    "status 1 sampai 31 Agustus",
  ]);
});

test("cliArgsFor maps a DM text reply with jid and channel", () => {
  assert.deepEqual(
    cliArgsFor({ kind: "text", text: "halo", jid: "628123@s.whatsapp.net", channel: "dm" }),
    ["bot-reply", "--text", "halo", "--jid", "628123@s.whatsapp.net", "--channel", "dm"],
  );
});

test("cliArgsFor maps an evidence upload", () => {
  assert.deepEqual(
    cliArgsFor({
      kind: "evidence",
      jid: "628123@s.whatsapp.net",
      filePath: "/data/evidence-uploads/1-a.jpg",
      caption: "bukti kerja",
    }),
    [
      "bot-evidence",
      "--jid",
      "628123@s.whatsapp.net",
      "--file",
      "/data/evidence-uploads/1-a.jpg",
      "--caption",
      "bukti kerja",
    ],
  );
});

test("cliArgsFor rejects malformed or unknown payloads", () => {
  assert.equal(cliArgsFor(null), null);
  assert.equal(cliArgsFor({ kind: "text" }), null);
  assert.equal(cliArgsFor({ kind: "evidence", jid: "628123@s.whatsapp.net" }), null);
  assert.equal(cliArgsFor({ kind: "unknown" }), null);
});
