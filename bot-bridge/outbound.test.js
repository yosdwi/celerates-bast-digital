"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { safeEqual, validJid } = require("./outbound");

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
