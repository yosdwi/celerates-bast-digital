"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const { RuntimeState } = require("./state");
const { Bridge } = require("./bridge");
const { DurableOutboundReceiptStore } = require("./gateway-receipts");
const {
  SessionOwnerGuard,
  clearStaleChromiumLocks,
  inspectSessionStorage,
} = require("./session-safety");
const { SessionSupervisor } = require("./session-supervisor");
const { MAX_MESSAGE_CHARS, MAX_REQUEST_ID_CHARS, safeEqual } = require("./helpers");

function getenv(name, fallback) {
  const value = (process.env[name] || "").trim();
  return value || fallback;
}

function envNumber(name, fallback) {
  const parsed = Number(getenv(name, String(fallback)));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

const DATA_DIR = getenv("BOT_DATA_DIR", "./data");
const AUTH_DIR = getenv("BOT_AUTH_DIR", path.join(DATA_DIR, "auth-whatsapp-web-js"));
const SETUP_HOST = getenv("BOT_SETUP_HOST", "127.0.0.1");
const SETUP_PORT = getenv("BOT_SETUP_PORT", "8090");
const WORKER_BASE_URL = getenv("BOT_WORKER_BASE_URL", "http://127.0.0.1:8091");
const WAIT_NOTICE_DELAY_MS = envNumber("BOT_WAIT_NOTICE_DELAY_MS", 2500);
const RECEIPT_MAX = envNumber("BOT_OUTBOUND_RECEIPT_MAX", 2048);
const OWNER_TTL_MS = envNumber("BOT_SESSION_OWNER_TTL_MS", 90_000);
const OWNER_HEARTBEAT_MS = envNumber("BOT_SESSION_OWNER_HEARTBEAT_MS", 15_000);
const MIN_FREE_BYTES = envNumber("BOT_SESSION_MIN_FREE_BYTES", 128 * 1024 * 1024);
const MIN_FREE_INODES = envNumber("BOT_SESSION_MIN_FREE_INODES", 256);
const SUPERVISOR_PROBE_MS = envNumber("BOT_SESSION_PROBE_MS", 15_000);
const SUPERVISOR_GRACE_MS = envNumber("BOT_SESSION_RECOVERY_GRACE_MS", 30_000);
const SUPERVISOR_WINDOW_MS = envNumber("BOT_SESSION_RECOVERY_WINDOW_MS", 15 * 60_000);
const SUPERVISOR_COOLDOWN_MS = envNumber("BOT_SESSION_RECOVERY_COOLDOWN_MS", 15 * 60_000);
const SUPERVISOR_MAX_ATTEMPTS = envNumber("BOT_SESSION_RECOVERY_MAX_ATTEMPTS", 3);

const RECEIPT_PATH = path.join(DATA_DIR, "whatsapp-outbound-receipts.json");
const OWNER_PATH = path.join(DATA_DIR, "whatsapp-web-session-owner.json");
const SUPERVISOR_PATH = path.join(DATA_DIR, "whatsapp-session-supervisor.json");

function configuredToken() {
  const tokenFile = getenv(
    "BOT_BRIDGE_TOKEN_FILE",
    getenv("SYNC_INGEST_TOKEN_FILE", "/run/secrets/sync_ingest_token"),
  );
  try {
    return fs.readFileSync(tokenFile, "utf8").trim();
  } catch {
    return "";
  }
}

function validDirectJid(raw) {
  return /^\d+@(c\.us|lid)$/.test(raw);
}

function validGroupJid(raw) {
  return /^\d+(?:-\d+)?@g\.us$/.test(raw);
}

function writeJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function nullable(value) {
  return value === "" ? null : value;
}

async function readJsonBody(req, maxBytes) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > maxBytes) {
        reject(new Error("body_too_large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch {
        reject(new Error("invalid_json"));
      }
    });
    req.on("error", reject);
  });
}

function bridgeAuthorized(req) {
  return safeEqual(req.headers["x-bridge-token"], configuredToken());
}

fs.mkdirSync(DATA_DIR, { recursive: true, mode: 0o750 });
fs.mkdirSync(AUTH_DIR, { recursive: true, mode: 0o750 });

const state = new RuntimeState(AUTH_DIR);
state.logf(`starting whatsapp-web.js transport; auth=${AUTH_DIR}`);

const storageSafety = inspectSessionStorage({
  dataDir: DATA_DIR,
  authDir: AUTH_DIR,
  minFreeBytes: MIN_FREE_BYTES,
  minFreeInodes: MIN_FREE_INODES,
});
if (!storageSafety.healthy) {
  state.logf(`session storage safety blocked startup: ${storageSafety.reasons.join(",")}`);
}

const ownerGuard = new SessionOwnerGuard({
  filePath: OWNER_PATH,
  ttlMs: OWNER_TTL_MS,
  heartbeatMs: OWNER_HEARTBEAT_MS,
  logf: (line) => state.logf(line),
});
const ownerAcquired = ownerGuard.acquire();
if (!ownerAcquired) {
  state.logf(
    `session owner conflict; existing owner=${ownerGuard.snapshot().conflict_owner_id || "unknown"}`,
  );
}

if (ownerAcquired && storageSafety.healthy) {
  const cleanup = clearStaleChromiumLocks(AUTH_DIR, {
    ownerGuard,
    storageSafety,
    logf: (line) => state.logf(line),
  });
  if (cleanup.cleared > 0) {
    state.logf(`cleared ${cleanup.cleared} stale Chromium singleton lock file(s)`);
  }
}

const bridge = new Bridge({
  state,
  authDir: AUTH_DIR,
  dataDir: DATA_DIR,
  workerBaseUrl: WORKER_BASE_URL,
  bridgeToken: configuredToken(),
  waitNoticeDelayMs: WAIT_NOTICE_DELAY_MS,
});

const outbound = new DurableOutboundReceiptStore({
  filePath: RECEIPT_PATH,
  maxReceipts: RECEIPT_MAX,
  logf: (line) => state.logf(line),
});

const supervisor = new SessionSupervisor({
  state,
  bridge,
  filePath: SUPERVISOR_PATH,
  ownerGuard,
  storageSafety,
  probeMs: SUPERVISOR_PROBE_MS,
  graceMs: SUPERVISOR_GRACE_MS,
  windowMs: SUPERVISOR_WINDOW_MS,
  cooldownMs: SUPERVISOR_COOLDOWN_MS,
  maxAttempts: SUPERVISOR_MAX_ATTEMPTS,
  logf: (line) => state.logf(line),
});

function messagingReady() {
  return bridge.isReady() && ownerGuard.acquired && storageSafety.healthy;
}

function operationalSnapshot() {
  const current = state.snapshot();
  const recovery = supervisor.snapshot();
  const owner = ownerGuard.snapshot();
  const receipts = outbound.snapshot();
  return {
    alive: true,
    ready: messagingReady(),
    connection: current.connection,
    me: current.me,
    qrDataUrl: nullable(current.qrDataUrl),
    pairingCode: nullable(current.pairingCode),
    operatorActionRequired: current.operatorActionRequired,
    operatorReason: nullable(current.operatorReason),
    connectionChangedAt: current.connectionChangedAt,
    recoveryState: recovery.recovery_state,
    recoveryReason: recovery.recovery_reason,
    recoveryPaused: recovery.paused,
    lastProbeAt: recovery.last_probe_at,
    lastReadyAt: recovery.last_ready_at,
    lastAckAt: recovery.last_ack_at,
    cooldownUntil: recovery.cooldown_until,
    recoveryAttempts: recovery.attempts_in_window,
    recoveryMaxAttempts: recovery.max_attempts,
    recoveryPolicyVersion: recovery.policy_version,
    appliedRecoveryPolicyVersion: recovery.applied_policy_version,
    ownerAcquired: owner.acquired,
    ownerConflictId: owner.conflict_owner_id,
    ownerConflictHeartbeatAt: owner.conflict_heartbeat_at,
    storageHealthy: storageSafety.healthy,
    storageReasons: storageSafety.reasons,
    freeBytes: storageSafety.free_bytes,
    freeInodes: storageSafety.free_inodes,
    receiptStoreHealthy: receipts.healthy,
    receiptStoreError: receipts.error,
    receiptSent: receipts.sent,
    receiptUnknown: receipts.unknown,
    receiptInFlight: receipts.in_flight,
    transport: "whatsapp-web.js",
  };
}

async function handleStatus(req, res) {
  if (!bridgeAuthorized(req)) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  writeJson(res, 200, operationalSnapshot());
}

function serializedId(value) {
  return value?._serialized ?? value?.$1 ?? "";
}

async function serializeParticipant(participant) {
  const jid = serializedId(participant.id);
  let contact = null;
  if (jid) {
    try {
      contact = await bridge.client.getContactById(jid);
    } catch (err) {
      state.logf(`contact metadata unavailable jid=${jid}: ${err.message}`);
    }
  }
  return {
    jid,
    display_name: String(contact?.pushname || contact?.name || contact?.shortName || ""),
    number: String(contact?.number || ""),
    is_my_contact: Boolean(contact?.isMyContact),
    is_admin: Boolean(participant.isAdmin),
    is_super_admin: Boolean(participant.isSuperAdmin),
  };
}

async function serializeGroup(chat) {
  const rawParticipants = Array.isArray(chat.participants) ? chat.participants : [];
  const participants = (await Promise.all(rawParticipants.map(serializeParticipant))).filter(
    (participant) => participant.jid !== "",
  );
  return {
    jid: serializedId(chat.id),
    subject: String(chat.name || ""),
    member_count: participants.length,
    participants,
  };
}

async function handleGroups(req, res) {
  if (!bridgeAuthorized(req)) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  if (!messagingReady()) {
    writeJson(res, 503, { status: "unavailable", error: "whatsapp_not_connected", groups: [] });
    return;
  }
  try {
    const chats = await bridge.client.getChats();
    const groups = await Promise.all(chats.filter((chat) => chat.isGroup).map(serializeGroup));
    state.groups = groups;
    writeJson(res, 200, {
      ready: true,
      connection: state.connection,
      discovered_at: new Date().toISOString(),
      groups,
    });
  } catch (err) {
    state.logf(`group/member discovery failed: ${err && err.stack ? err.stack : err}`);
    writeJson(res, 503, { status: "unavailable", error: "group_discovery_failed", groups: [] });
  }
}

async function handleLeaveGroups(req, res) {
  if (!bridgeAuthorized(req)) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  if (!messagingReady()) {
    writeJson(res, 503, { status: "unavailable", error: "whatsapp_not_connected" });
    return;
  }
  let payload;
  try {
    payload = await readJsonBody(req, 16 * 1024);
  } catch {
    writeJson(res, 400, { status: "invalid", error: "invalid_json" });
    return;
  }
  const jids = Array.isArray(payload.jids) ? payload.jids.map((v) => String(v).trim()) : [];
  if (jids.length === 0 || jids.some((jid) => !validGroupJid(jid))) {
    writeJson(res, 422, { status: "invalid", error: "invalid_group_jid" });
    return;
  }
  const results = [];
  for (const jid of jids) {
    try {
      const chat = await bridge.client.getChatById(jid);
      if (!chat || !chat.isGroup) {
        results.push({ jid, status: "not_found" });
        continue;
      }
      await chat.leave();
      await chat.delete();
      results.push({ jid, status: "left" });
      state.logf(`left and deleted group jid=${jid}`);
    } catch (err) {
      results.push({ jid, status: "failed", error: err.message });
      state.logf(`leave group failed jid=${jid}: ${err && err.stack ? err.stack : err}`);
    }
  }
  writeJson(res, 200, { status: "done", results });
}

async function handleSendOutbound(req, res, jidValidator) {
  if (!bridgeAuthorized(req)) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  if (!messagingReady()) {
    writeJson(res, 503, { status: "unavailable", error: "whatsapp_not_connected" });
    return;
  }
  let payload;
  try {
    payload = await readJsonBody(req, 16 * 1024);
  } catch {
    writeJson(res, 400, { status: "invalid", error: "invalid_json" });
    return;
  }
  const jid = String(payload.jid || "").trim();
  const text = String(payload.text || "").trim();
  const requestId = String(payload.request_id || "").trim();
  if (
    !jidValidator(jid) ||
    !text ||
    text.length > MAX_MESSAGE_CHARS ||
    !requestId ||
    requestId.length > MAX_REQUEST_ID_CHARS
  ) {
    writeJson(res, 422, { status: "invalid", error: "invalid_message_request" });
    return;
  }

  const result = await outbound.run(requestId, jid, text, async () => {
    state.logf(`outbound start request=${requestId} target=${jid} text_len=${text.length}`);
    try {
      const providerMessageId = await bridge.sendText(jid, text);
      state.logf(`outbound ack request=${requestId} provider=${providerMessageId} target=${jid}`);
      supervisor.markAck();
      return { status: "sent", provider_message_id: providerMessageId };
    } catch (err) {
      state.logf(`outbound failed request=${requestId}: ${err && err.stack ? err.stack : err}`);
      return { status: "unavailable", error: "send_failed" };
    }
  });
  if (result.conflict) {
    writeJson(res, 409, { status: "invalid", error: "request_id_conflict" });
    return;
  }
  writeJson(res, result.status === "sent" ? 200 : 503, result);
}

async function beginControlledPairing() {
  if (!ownerGuard.acquired) return { accepted: false, reason: "session_owner_not_acquired" };
  if (!storageSafety.healthy) return { accepted: false, reason: "session_storage_unhealthy" };
  if (messagingReady()) return { accepted: false, reason: "already_ready" };
  if (!state.operatorActionRequired && state.connection !== "pairing-required") {
    return { accepted: false, reason: "pairing_not_required" };
  }

  state.clearOperatorAction();
  state.setConnection("starting");
  supervisor.resume();
  state.logf("operator explicitly requested controlled WhatsApp pairing");
  bridge.start().catch((err) => {
    state.setConnection("failed");
    state.logf(`pairing restart failed: ${err.stack || err}`);
  });
  return { accepted: true, reason: "pairing_started" };
}

async function handleRecoveryControl(req, res, action) {
  if (!bridgeAuthorized(req)) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  if (action === "pause") {
    supervisor.pause();
    writeJson(res, 200, { accepted: true, reason: "paused" });
    return;
  }
  if (action === "resume") {
    supervisor.resume();
    writeJson(res, 200, { accepted: true, reason: "resumed" });
    return;
  }
  if (action === "reconnect") {
    const result = await supervisor.requestReconnect();
    writeJson(res, result.accepted ? 202 : 409, result);
    return;
  }
  if (action === "pair") {
    const result = await beginControlledPairing();
    writeJson(res, result.accepted ? 202 : 409, result);
    return;
  }
  writeJson(res, 404, { status: "not_found" });
}

function setupPageHtml() {
  const s = state.snapshot();
  const ops = operationalSnapshot();
  let pairing = "<p>Tidak ada QR aktif.</p>";
  if (ops.ready) {
    pairing = "<p>Sudah terhubung. Tidak perlu pairing lagi.</p>";
  } else if (s.qrDataUrl) {
    pairing = `<img alt="WhatsApp QR" src="${s.qrDataUrl}" width="320" height="320">`;
  }
  if (s.pairingCode) {
    pairing += `<p>Atau masukkan kode ini di WhatsApp &gt; Perangkat tertaut &gt; Tautkan dengan nomor telepon: <strong>${escapeHtml(s.pairingCode)}</strong></p>`;
  }
  if (s.operatorActionRequired && s.connection === "pairing-required") {
    pairing =
      `<p><strong>Pairing otomatis diblokir setelah disconnect permanen.</strong></p>` +
      `<p>${escapeHtml(s.operatorReason)}</p>` +
      `<form method="post" action="/pair"><button type="submit">Mulai pairing terkontrol</button></form>`;
  }
  const refresh = !ops.ready && s.connection !== "pairing-required" ? '<meta http-equiv="refresh" content="5">' : "";
  const rows =
    s.groups
      .map((group) => `<tr><td>${escapeHtml(group.subject)}</td><td><code>${escapeHtml(group.jid)}</code></td></tr>`)
      .join("") || `<tr><td colspan="2">Belum ada grup terbaca.</td></tr>`;
  return (
    `<!doctype html><html lang="id"><head><meta charset="utf-8">${refresh}` +
    `<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setup BAST Bot</title>` +
    `<style>body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:52rem;padding:0 1rem;line-height:1.5}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}pre{background:#f5f5f5;padding:.75rem;overflow:auto;max-height:18rem}.status{font-weight:600}.warn{background:#fff3cd;padding:.75rem;border-radius:.25rem}</style>` +
    `</head><body><h1>Setup BAST Bot — whatsapp-web.js</h1>` +
    `<p class="status">Status: ${escapeHtml(s.connection)} — ready=${ops.ready} — ${escapeHtml(s.me)}</p>` +
    `<p>Recovery: ${escapeHtml(ops.recoveryState)}${ops.recoveryReason ? ` — ${escapeHtml(ops.recoveryReason)}` : ""}</p>` +
    `<h2>1. Pairing WhatsApp</h2>${pairing}` +
    `<h2>2. Grup terbaca</h2><table><thead><tr><th>Nama grup</th><th>JID</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<h2>Log</h2><pre>${escapeHtml(s.logs.join("\n"))}</pre></body></html>`
  );
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      writeJson(res, 200, operationalSnapshot());
      return;
    }
    if (req.method === "GET" && url.pathname === "/ready") {
      const snapshot = operationalSnapshot();
      writeJson(res, snapshot.ready ? 200 : 503, snapshot);
      return;
    }
    if (req.method === "GET" && url.pathname === "/internal/v1/status") {
      await handleStatus(req, res);
      return;
    }
    if (req.method === "GET" && url.pathname === "/internal/v1/groups") {
      await handleGroups(req, res);
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/groups/leave") {
      await handleLeaveGroups(req, res);
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/messages") {
      await handleSendOutbound(req, res, validDirectJid);
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/group-messages") {
      await handleSendOutbound(req, res, validGroupJid);
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/recovery/pause") {
      await handleRecoveryControl(req, res, "pause");
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/recovery/resume") {
      await handleRecoveryControl(req, res, "resume");
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/recovery/reconnect") {
      await handleRecoveryControl(req, res, "reconnect");
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/pair") {
      await handleRecoveryControl(req, res, "pair");
      return;
    }
    if (req.method === "POST" && url.pathname === "/pair") {
      await beginControlledPairing();
      res.writeHead(303, { location: "/" });
      res.end();
      return;
    }
    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(setupPageHtml());
      return;
    }
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("not found");
  } catch (err) {
    state.logf(`request handler error ${url.pathname}: ${err.stack || err}`);
    writeJson(res, 500, { status: "error" });
  }
});

server.listen(Number(SETUP_PORT), SETUP_HOST, () => {
  state.logf(`setup/status HTTP on http://${SETUP_HOST}:${SETUP_PORT}`);
});

if (!ownerAcquired) {
  state.setConnection("blocked");
  state.logf("WhatsApp client initialization blocked by active session owner lease");
} else if (!storageSafety.healthy) {
  state.setConnection("blocked");
  state.logf("WhatsApp client initialization blocked by session storage safety gate");
} else if (state.operatorActionRequired) {
  state.setConnection("pairing-required");
  state.logf(
    `automatic pairing blocked after permanent disconnect; explicit operator action required: ${state.operatorReason}`,
  );
} else {
  bridge.start().catch((err) => {
    state.setConnection("failed");
    state.logf(`initialize failed: ${err.stack || err}`);
  });
}
supervisor.start();

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  state.logf(`shutdown requested: ${signal}`);
  supervisor.stop();
  await bridge.client.destroy().catch(() => {});
  ownerGuard.release();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 5000).unref?.();
}

process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));
