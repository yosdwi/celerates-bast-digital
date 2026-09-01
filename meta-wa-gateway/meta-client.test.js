"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { MetaClient, MetaGraphError } = require("./meta-client");

function config() {
  return {
    graphBaseUrl: "https://graph.example",
    graphVersion: "v26.0",
    phoneNumberId: "phone-id",
    accessToken: "secret-token",
    requestTimeoutMs: 1000,
  };
}

test("text replies use the official messages endpoint and reply context", async () => {
  let request = null;
  const client = new MetaClient(config(), async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ messages: [{ id: "wamid.out" }] }), { status: 200 });
  });
  assert.equal(await client.sendText("62812", "Halo", "wamid.in"), "wamid.out");
  assert.equal(request.url, "https://graph.example/v26.0/phone-id/messages");
  assert.equal(request.options.headers.Authorization, "Bearer secret-token");
  assert.deepEqual(JSON.parse(request.options.body), {
    messaging_product: "whatsapp",
    to: "62812",
    type: "text",
    text: { preview_url: true, body: "Halo" },
    context: { message_id: "wamid.in" },
  });
});

test("utility templates map body parameters without provider leakage", async () => {
  let body = null;
  const client = new MetaClient(config(), async (_url, options) => {
    body = JSON.parse(options.body);
    return new Response(JSON.stringify({ messages: [{ id: "wamid.template" }] }), { status: 200 });
  });
  await client.sendTemplate("62812", "bast_action_required_v1", "id", ["Lengkapi BAST"]);
  assert.deepEqual(body.template, {
    name: "bast_action_required_v1",
    language: { code: "id" },
    components: [{ type: "body", parameters: [{ type: "text", text: "Lengkapi BAST" }] }],
  });
});

test("Graph API errors preserve Meta code for policy-aware handling", async () => {
  const client = new MetaClient(config(), async () => new Response(JSON.stringify({
    error: { message: "Re-engagement message", code: 131047 },
  }), { status: 400 }));
  await assert.rejects(
    () => client.sendText("62812", "late"),
    (error) => error instanceof MetaGraphError && error.status === 400 && error.code === "131047",
  );
});
