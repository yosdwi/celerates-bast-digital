"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { parsedEnvelope, interactivePayload, extractUrl } = require("./replies");

test("three compact actions render as native reply buttons", () => {
  const payload = interactivePayload({
    text: "Pilih menu",
    footer: "Digital BAST",
    actions: [
      { id: "bast-saya", label: "BAST Saya" },
      { id: "attendance", label: "Attendance" },
      { id: "tasklist", label: "Task Evidence" },
    ],
  });
  assert.equal(payload.type, "button");
  assert.deepEqual(payload.action.buttons.map((item) => item.reply.id), [
    "bast-saya",
    "attendance",
    "tasklist",
  ]);
});

test("larger menus render as a native list with at most ten rows", () => {
  const payload = interactivePayload({
    text: "Pilih",
    actions: Array.from({ length: 12 }, (_, index) => ({ id: `a${index}`, label: `Menu ${index}` })),
  });
  assert.equal(payload.type, "list");
  assert.equal(payload.action.sections[0].rows.length, 10);
});

test("Talent Mobile URL is separated for a native CTA", () => {
  assert.deepEqual(extractUrl("Buka Attendance:\nhttps://bast.example/talent/mobile?t=x"), {
    text: "Buka Attendance:",
    url: "https://bast.example/talent/mobile?t=x",
  });
});

test("invalid JSON remains a plain worker reply", () => {
  assert.equal(parsedEnvelope("normal reply"), null);
});
