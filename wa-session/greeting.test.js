"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { firstName, waitingReply } = require("./greeting");

test("firstName pulls the bare first word out of a decorated pushName", () => {
  assert.equal(firstName("~ Putri 🌸"), "Putri");
  assert.equal(firstName("Putri Wulandari"), "Putri");
  assert.equal(firstName(""), null);
  assert.equal(firstName(undefined), null);
});

test("waitingReply greets by first name when a pushName is available", () => {
  for (let i = 0; i < 20; i += 1) {
    assert.match(waitingReply("Putri Wulandari"), /\bkak Putri\b/);
  }
});

test("waitingReply falls back to a nameless variant without a pushName", () => {
  for (let i = 0; i < 20; i += 1) {
    assert.doesNotMatch(waitingReply(undefined), /\bkak\b/);
  }
});
