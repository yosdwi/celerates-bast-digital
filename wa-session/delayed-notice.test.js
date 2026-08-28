"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { withDelayedNotice } = require("./delayed-notice");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("fast operations do not emit a wait notice", async () => {
  let notices = 0;
  const result = await withDelayedNotice(
    async () => "done",
    async () => {
      notices += 1;
    },
    20,
  );
  await sleep(30);
  assert.equal(result, "done");
  assert.equal(notices, 0);
});

test("slow operations emit exactly one wait notice", async () => {
  let notices = 0;
  const result = await withDelayedNotice(
    async () => {
      await sleep(35);
      return "done";
    },
    async () => {
      notices += 1;
    },
    10,
  );
  assert.equal(result, "done");
  assert.equal(notices, 1);
});

test("a wait-notice failure never changes the business result", async () => {
  const result = await withDelayedNotice(
    async () => {
      await sleep(20);
      return "done";
    },
    async () => {
      throw new Error("transport failed");
    },
    5,
  );
  assert.equal(result, "done");
});
