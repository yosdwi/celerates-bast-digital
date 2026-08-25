"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { safeEqual, sendOutboundOnce, validJid } = require("./outbound");

test("safeEqual only accepts equal non-empty tokens", () => {
  assert.equal(safeEqual("secret-value", "secret-value"), true);
  assert.equal(safeEqual("secret-value", "other-value"), false);
  assert.equal(safeEqual("", ""), false);
  assert.equal(safeEqual(undefined, "secret-value"), false);
});

test("validJid accepts direct WhatsApp identities only", () => {
  assert.equal(validJid("628123@s.whatsapp.net"), true);
  assert.equal(validJid("12345@lid"), true);
  assert.equal(validJid("12345@g.us"), false);
  assert.equal(validJid("not-a-jid"), false);
});

test("sendOutboundOnce joins concurrent retries and reuses the successful receipt", async () => {
  let sends = 0;
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const state = {
    socket: {
      async sendMessage() {
        sends += 1;
        await waiting;
        return { key: { id: "wa-message-1" } };
      },
    },
  };
  const logs = [];
  const log = (line) => logs.push(line);
  const requestId = "request-dedupe-1";
  const jid = "628123@s.whatsapp.net";
  const text = "Please review the current evidence blocker.";

  const first = sendOutboundOnce(state, jid, text, requestId, log);
  const second = sendOutboundOnce(state, jid, text, requestId, log);
  release();
  const [firstResult, secondResult] = await Promise.all([first, second]);
  const thirdResult = await sendOutboundOnce(state, jid, text, requestId, log);

  assert.equal(sends, 1);
  assert.deepEqual(firstResult, secondResult);
  assert.deepEqual(thirdResult, firstResult);
  assert.equal(firstResult.statusCode, 200);
  assert.equal(firstResult.payload.provider_message_id, "wa-message-1");
  assert.equal(logs.some((line) => line.includes("joined in-flight")), true);
  assert.equal(logs.some((line) => line.includes("deduped")), true);
});

test("sendOutboundOnce rejects request-id reuse for a different message", async () => {
  let sends = 0;
  const state = {
    socket: {
      async sendMessage() {
        sends += 1;
        return { key: { id: "wa-message-2" } };
      },
    },
  };
  const requestId = "request-dedupe-conflict";
  const jid = "628123@s.whatsapp.net";

  const first = await sendOutboundOnce(state, jid, "Message A", requestId, () => {});
  const conflicting = await sendOutboundOnce(state, jid, "Message B", requestId, () => {});

  assert.equal(first.statusCode, 200);
  assert.equal(conflicting.statusCode, 409);
  assert.equal(conflicting.payload.error, "request_id_conflict");
  assert.equal(sends, 1);
});
