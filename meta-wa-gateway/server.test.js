"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");

const { Gateway, createServer, validSignature } = require("./server");
const { MetaGraphError } = require("./meta-client");

function config() {
  return {
    host: "127.0.0.1",
    port: 0,
    graphVersion: "v26.0",
    phoneNumberId: "phone-id",
    businessPhone: "+62881",
    accessToken: "access",
    appSecret: "app-secret",
    verifyToken: "verify-me",
    bridgeToken: "bridge-secret",
    databaseDsn: "postgres://unused",
    workerBaseUrl: "http://worker",
    dataDir: "/tmp",
    utilityTemplate: "bast_action_required_v1",
    templateLanguage: "id",
    graphBaseUrl: "https://graph.example",
    requestTimeoutMs: 1000,
  };
}

function fakeDatabase() {
  return {
    ready: async () => true,
    enqueueInbound: async () => {},
    pendingInbound: async () => [],
    claimInbound: async () => true,
    completeInbound: async () => {},
    failInbound: async () => {},
    recordStatus: async () => {},
    claimOutbound: async () => ({ action: "send" }),
    completeOutbound: async () => {},
    failOutbound: async () => {},
  };
}

async function listening(dependencies = {}) {
  const built = createServer(config(), dependencies);
  await new Promise((resolve) => built.server.listen(0, "127.0.0.1", resolve));
  const address = built.server.address();
  return { ...built, base: `http://127.0.0.1:${address.port}` };
}

test("webhook signature uses the raw request body", () => {
  const raw = Buffer.from('{"entry":[]}');
  const signature = `sha256=${crypto.createHmac("sha256", "app-secret").update(raw).digest("hex")}`;
  assert.equal(validSignature(raw, signature, "app-secret"), true);
  assert.equal(validSignature(Buffer.from("changed"), signature, "app-secret"), false);
});

test("Meta webhook challenge is verified without exposing the token", async (t) => {
  const app = await listening({ gateway: { database: fakeDatabase() } });
  t.after(() => app.server.close());
  const response = await fetch(`${app.base}/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345`);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "12345");
});

test("signed webhook is acknowledged before scheduled processing", async (t) => {
  let scheduled = null;
  const app = await listening({
    gateway: {
      database: fakeDatabase(),
      async acceptWebhook() {},
      scheduleWebhook(payload) {
        scheduled = payload;
      },
    },
  });
  t.after(() => app.server.close());
  const raw = JSON.stringify({ object: "whatsapp_business_account", entry: [] });
  const signature = `sha256=${crypto.createHmac("sha256", "app-secret").update(raw).digest("hex")}`;
  const response = await fetch(`${app.base}/webhooks/whatsapp`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-hub-signature-256": signature },
    body: raw,
  });
  assert.equal(response.status, 200);
  assert.equal(scheduled.object, "whatsapp_business_account");
});

test("invalid webhook signature is rejected", async (t) => {
  const app = await listening({ gateway: { database: fakeDatabase() } });
  t.after(() => app.server.close());
  const response = await fetch(`${app.base}/webhooks/whatsapp`, {
    method: "POST",
    headers: { "x-hub-signature-256": "sha256=invalid" },
    body: "{}",
  });
  assert.equal(response.status, 401);
});

test("Gateway renders worker interactive envelopes through Meta", async () => {
  let sent = null;
  const meta = {
    markRead: async () => {},
    sendInteractive: async (to, interactive) => {
      sent = { to, interactive };
      return "wamid.out";
    },
  };
  const database = fakeDatabase();
  const gateway = new Gateway(config(), {
    meta,
    database,
    fetchImpl: async () => new Response(JSON.stringify({
      ok: true,
      text: JSON.stringify({
        kind: "interactive",
        text: "Pilih",
        actions: [{ id: "attendance", label: "Attendance" }],
      }),
    }), { status: 200 }),
    logger: { error() {} },
  });
  await gateway.processMessage({ id: "wamid.in", waId: "6281", kind: "text", text: "menu" });
  assert.equal(sent.to, "6281");
  assert.equal(sent.interactive.action.buttons[0].reply.id, "attendance");
});

test("application-initiated outbound defaults to utility template", async () => {
  const calls = [];
  const meta = {
    async sendTemplate(to, template, language, parameters) {
      calls.push({ to, template, language, parameters });
      return "wamid.template";
    },
  };
  const database = fakeDatabase();
  let completed = null;
  database.completeOutbound = async (requestId, messageId) => { completed = { requestId, messageId }; };
  const gateway = new Gateway(config(), { meta, database });
  const result = await gateway.sendOutbound({
    request_id: "manual-follow-up:1",
    jid: "62812@s.whatsapp.net",
    text: "BAST masih perlu dilengkapi",
  });
  assert.equal(result, "wamid.template");
  assert.deepEqual(calls[0], {
    to: "62812",
    template: "bast_action_required_v1",
    language: "id",
    parameters: ["BAST masih perlu dilengkapi"],
  });
  assert.deepEqual(completed, { requestId: "manual-follow-up:1", messageId: "wamid.template" });
});

test("explicit service-window text falls back to utility template on 131047", async () => {
  const calls = [];
  const meta = {
    async sendText() { throw new MetaGraphError("Re-engagement message", 400, "131047"); },
    async sendTemplate(...args) { calls.push(args); return "wamid.fallback"; },
  };
  const gateway = new Gateway(config(), { meta, database: fakeDatabase() });
  const result = await gateway.sendOutbound({
    request_id: "explicit-text:1",
    jid: "62812@s.whatsapp.net",
    kind: "text",
    text: "Follow up",
  });
  assert.equal(result, "wamid.fallback");
  assert.equal(calls.length, 1);
});

test("webhook returns retryable failure when durable enqueue is unavailable", async (t) => {
  const app = await listening({
    gateway: {
      database: fakeDatabase(),
      async acceptWebhook() { throw new Error("db down"); },
      scheduleWebhook() { assert.fail("must not schedule an unpersisted webhook"); },
      logger: { error() {} },
    },
  });
  t.after(() => app.server.close());
  const raw = JSON.stringify({ object: "whatsapp_business_account", entry: [] });
  const signature = `sha256=${crypto.createHmac("sha256", "app-secret").update(raw).digest("hex")}`;
  const response = await fetch(`${app.base}/webhooks/whatsapp`, {
    method: "POST",
    headers: { "x-hub-signature-256": signature },
    body: raw,
  });
  assert.equal(response.status, 503);
});
