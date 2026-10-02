"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { DurableOutboundReceiptStore, payloadFingerprint } = require("./gateway-receipts");

function temporaryStore(maxReceipts = 16) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wwjs-receipts-"));
  const filePath = path.join(dir, "receipts.json");
  return {
    dir,
    filePath,
    store: new DurableOutboundReceiptStore({ filePath, maxReceipts }),
  };
}

function cleanup(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

test("sent receipt survives restart and replays without a second send", async () => {
  const fixture = temporaryStore();
  let sends = 0;
  try {
    const first = await fixture.store.run("req-1", "6281@c.us", "hello", async () => {
      sends += 1;
      return { status: "sent", provider_message_id: "wa-1" };
    });
    const restarted = new DurableOutboundReceiptStore({ filePath: fixture.filePath });
    const replay = await restarted.run("req-1", "6281@c.us", "hello", async () => {
      sends += 1;
      return { status: "sent", provider_message_id: "wa-2" };
    });

    assert.deepEqual(first, { status: "sent", provider_message_id: "wa-1" });
    assert.deepEqual(replay, first);
    assert.equal(sends, 1);
    assert.equal(restarted.snapshot().sent, 1);
  } finally {
    cleanup(fixture.dir);
  }
});

test("same request id with a different payload remains a strict conflict after restart", async () => {
  const fixture = temporaryStore();
  try {
    await fixture.store.run("req-2", "6281@c.us", "hello", async () => ({ status: "sent" }));
    const restarted = new DurableOutboundReceiptStore({ filePath: fixture.filePath });
    const conflict = await restarted.run("req-2", "6281@c.us", "different", async () => ({
      status: "sent",
    }));

    assert.deepEqual(conflict, { conflict: true });
  } finally {
    cleanup(fixture.dir);
  }
});

test("accepted receipt from an interrupted process becomes unknown and is never resent", async () => {
  const fixture = temporaryStore();
  let sends = 0;
  try {
    fs.writeFileSync(
      fixture.filePath,
      JSON.stringify({
        version: 1,
        receipts: [
          {
            request_id: "req-3",
            fingerprint: payloadFingerprint("6281@c.us", "hello"),
            state: "accepted",
            result: null,
            updated_at: new Date().toISOString(),
          },
        ],
      }),
    );
    const restarted = new DurableOutboundReceiptStore({ filePath: fixture.filePath });
    const replay = await restarted.run("req-3", "6281@c.us", "hello", async () => {
      sends += 1;
      return { status: "sent" };
    });

    assert.deepEqual(replay, { status: "unavailable", error: "delivery_outcome_unknown" });
    assert.equal(sends, 0);
    assert.equal(restarted.snapshot().unknown, 1);
  } finally {
    cleanup(fixture.dir);
  }
});

test("concurrent accepted requests are both durable before either send finishes", async () => {
  const fixture = temporaryStore();
  let releaseFirst;
  let releaseSecond;
  try {
    const first = fixture.store.run(
      "concurrent-1",
      "6281@c.us",
      "first",
      () => new Promise((resolve) => { releaseFirst = resolve; }),
    );
    const second = fixture.store.run(
      "concurrent-2",
      "6282@c.us",
      "second",
      () => new Promise((resolve) => { releaseSecond = resolve; }),
    );

    const persisted = JSON.parse(fs.readFileSync(fixture.filePath, "utf8"));
    const accepted = new Set(
      persisted.receipts
        .filter((record) => record.state === "accepted")
        .map((record) => record.request_id),
    );
    assert.deepEqual(accepted, new Set(["concurrent-1", "concurrent-2"]));

    releaseFirst({ status: "sent", provider_message_id: "wa-1" });
    releaseSecond({ status: "sent", provider_message_id: "wa-2" });
    await Promise.all([first, second]);
  } finally {
    cleanup(fixture.dir);
  }
});

test("ambiguous send failure becomes durable unknown instead of retrying blindly", async () => {
  const fixture = temporaryStore();
  let sends = 0;
  try {
    const first = await fixture.store.run("req-4", "6281@c.us", "hello", async () => {
      sends += 1;
      return { status: "unavailable", error: "send_failed" };
    });
    const second = await fixture.store.run("req-4", "6281@c.us", "hello", async () => {
      sends += 1;
      return { status: "sent" };
    });

    assert.deepEqual(first, { status: "unavailable", error: "delivery_outcome_unknown" });
    assert.deepEqual(second, first);
    assert.equal(sends, 1);
  } finally {
    cleanup(fixture.dir);
  }
});

test("durable receipts stay bounded", async () => {
  const fixture = temporaryStore(2);
  try {
    for (const id of ["one", "two", "three"]) {
      await fixture.store.run(id, "6281@c.us", id, async () => ({ status: "sent" }));
    }
    const restarted = new DurableOutboundReceiptStore({
      filePath: fixture.filePath,
      maxReceipts: 2,
    });

    assert.equal(restarted.snapshot().retained, 2);
  } finally {
    cleanup(fixture.dir);
  }
});
