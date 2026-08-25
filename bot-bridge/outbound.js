"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");

const DEFAULT_TOKEN_FILE = "/run/secrets/sync_ingest_token";
const MAX_BODY_BYTES = 16 * 1024;
const MAX_MESSAGE_CHARS = 4000;
const MAX_REQUEST_ID_CHARS = 128;

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (a.length === 0 || a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function configuredToken() {
  const tokenFile = process.env.BOT_BRIDGE_TOKEN_FILE || process.env.SYNC_INGEST_TOKEN_FILE || DEFAULT_TOKEN_FILE;
  try {
    return fs.readFileSync(tokenFile, "utf8").trim();
  } catch {
    return "";
  }
}

function writeJson(response, statusCode, payload) {
  response.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > MAX_BODY_BYTES) {
        reject(new Error("body_too_large"));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch {
        reject(new Error("invalid_json"));
      }
    });
    request.on("error", reject);
  });
}

function validJid(jid) {
  return typeof jid === "string" && (jid.endsWith("@s.whatsapp.net") || jid.endsWith("@lid"));
}

async function handleOutboundRequest(request, response, state, log) {
  const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);
  if (request.method !== "POST" || url.pathname !== "/internal/v1/messages") return false;

  const expected = configuredToken();
  const supplied = request.headers["x-bridge-token"];
  if (!expected || !safeEqual(supplied, expected)) {
    writeJson(response, 403, { status: "forbidden" });
    return true;
  }
  if (state.connection !== "connected" || !state.socket) {
    writeJson(response, 503, { status: "unavailable", error: "whatsapp_not_connected" });
    return true;
  }

  let payload;
  try {
    payload = await readJsonBody(request);
  } catch (error) {
    writeJson(response, 400, { status: "invalid", error: String(error.message || error) });
    return true;
  }
  const jid = payload.jid;
  const text = typeof payload.text === "string" ? payload.text.trim() : "";
  const requestId = typeof payload.request_id === "string" ? payload.request_id.trim() : "";
  if (
    !validJid(jid) ||
    !text ||
    text.length > MAX_MESSAGE_CHARS ||
    !requestId ||
    requestId.length > MAX_REQUEST_ID_CHARS
  ) {
    writeJson(response, 422, { status: "invalid", error: "invalid_message_request" });
    return true;
  }

  try {
    const sent = await state.socket.sendMessage(jid, { text });
    const providerMessageId = sent?.key?.id || null;
    log(`outbound follow-up sent request=${requestId} provider=${providerMessageId || "unknown"}`);
    writeJson(response, 200, {
      status: "sent",
      provider_message_id: providerMessageId,
    });
  } catch (error) {
    log(`outbound follow-up failed request=${requestId}: ${error}`);
    writeJson(response, 503, { status: "unavailable", error: "send_failed" });
  }
  return true;
}

module.exports = { handleOutboundRequest, safeEqual, validJid };
