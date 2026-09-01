"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { GatewayDatabase, payloadHash } = require("./database");

test("payload hash is deterministic and changes with content", () => {
  assert.equal(payloadHash({ a: 1 }), payloadHash({ a: 1 }));
  assert.notEqual(payloadHash({ a: 1 }), payloadHash({ a: 2 }));
});

test("pending outbound can only be reclaimed after the stale guard", async () => {
  const queries = [];
  const pool = {
    async query(sql) {
      queries.push(sql);
      if (queries.length === 1) return { rowCount: 0, rows: [] };
      if (queries.length === 2) {
        return { rowCount: 1, rows: [{ payload_hash: payloadHash({ text: "x" }), status: "pending" }] };
      }
      return { rowCount: 1, rows: [{ request_id: "r1" }] };
    },
  };
  const database = new GatewayDatabase("unused", pool);
  const result = await database.claimOutbound("r1", { text: "x" });
  assert.equal(result.action, "send");
  assert.match(queries[2], /updated_at < now\(\) - interval '5 minutes'/);
});
