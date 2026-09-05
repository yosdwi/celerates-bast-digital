"use strict";

// Prototype wa-session replacement (whatsapp-web.js). See README.md for how
// to run this in isolation and what it does/doesn't prove yet. Contract
// (routes, request/response shapes, x-bridge-token auth) matches
// whatsmeow-session/main.go exactly so this is a real drop-in test, not a
// simplified stand-in.

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const { RuntimeState } = require("./state");
const { Bridge } = require("./bridge");
const { MAX_MESSAGE_CHARS, MAX_REQUEST_ID_CHARS, safeEqual, OutboundDedupeStore } = require("./helpers");

function getenv(name, fallback) {
  const v = (process.env[name] || "").trim();
  return v || fallback;
}

const DATA_DIR = getenv("BOT_DATA_DIR", "./data");
const AUTH_DIR = getenv("BOT_AUTH_DIR", path.join(DATA_DIR, "auth-whatsapp-web-js"));
const SETUP_HOST = getenv("BOT_SETUP_HOST", "127.0.0.1");
const SETUP_PORT = getenv("BOT_SETUP_PORT", "8090");
const WORKER_BASE_URL = getenv("BOT_WORKER_BASE_URL", "http://127.0.0.1:8091");
const WAIT_NOTICE_DELAY_MS = Number(getenv("BOT_WAIT_NOTICE_DELAY_MS", "2500"));

function configuredToken() {
  const tokenFile = getenv("BOT_BRIDGE_TOKEN_FILE", getenv("SYNC_INGEST_TOKEN_FILE", "/run/secrets/sync_ingest_token"));
  try {
    return fs.readFileSync(tokenFile, "utf8").trim();
  } catch {
    return "";
  }
}

function validDirectJid(raw) {
  // whatsapp-web.js direct-chat JIDs look like "<digits>@c.us" (classic) or
  // "<digits>@lid" (privacy/LID addressing) -- mirrors whatsmeow-session's
  // validDirectJID accepting both DefaultUserServer and HiddenUserServer.
  return /^\d+@(c\.us|lid)$/.test(raw);
}

fs.mkdirSync(AUTH_DIR, { recursive: true, mode: 0o750 });
fs.mkdirSync(DATA_DIR, { recursive: true, mode: 0o750 });

// Chromium refuses to launch against a profile that still has a
// SingletonLock/-Socket/-Cookie from a previous run -- it can't tell a
// stale lock (previous container didn't shut down cleanly before this one
// started) apart from a real concurrent process. Our deploy model
// guarantees at most one container holds this volume at a time (compose
// always stops the old one before starting a new one), so on OUR OWN
// startup any such lock is by definition stale -- safe to clear, unlike
// deleting it while a process might actually be running.
function clearStaleChromiumLocks(root) {
  let cleared = 0;
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
      } else if (/^Singleton(Lock|Socket|Cookie)$/.test(entry.name)) {
        try {
          fs.rmSync(full, { force: true });
          cleared += 1;
        } catch (err) {
          state.logf(`failed to clear stale lock ${full}: ${err.message}`);
        }
      }
    }
  }
  return cleared;
}

const state = new RuntimeState(AUTH_DIR);
state.logf(`starting whatsapp-web.js transport; auth=${AUTH_DIR}`);

const clearedLocks = clearStaleChromiumLocks(AUTH_DIR);
if (clearedLocks > 0) state.logf(`cleared ${clearedLocks} stale Chromium singleton lock file(s) from a previous run`);

const bridge = new Bridge({
  state,
  authDir: AUTH_DIR,
  dataDir: DATA_DIR,
  workerBaseUrl: WORKER_BASE_URL,
  bridgeToken: configuredToken(),
  waitNoticeDelayMs: WAIT_NOTICE_DELAY_MS,
});

const outbound = new OutboundDedupeStore();

function writeJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function nullable(v) {
  return v === "" ? null : v;
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

async function handleStatus(req, res) {
  if (!safeEqual(req.headers["x-bridge-token"], configuredToken())) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  const s = state.snapshot();
  writeJson(res, 200, {
    connection: s.connection,
    ready: bridge.isReady(),
    me: s.me,
    qrDataUrl: nullable(s.qrDataUrl),
    pairingCode: nullable(s.pairingCode),
    operatorActionRequired: s.operatorActionRequired,
    operatorReason: nullable(s.operatorReason),
    connectionChangedAt: s.connectionChangedAt,
    transport: "whatsapp-web.js",
  });
}

async function handleSendOutbound(req, res) {
  if (!safeEqual(req.headers["x-bridge-token"], configuredToken())) {
    writeJson(res, 403, { status: "forbidden" });
    return;
  }
  if (!bridge.isReady()) {
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
  if (!validDirectJid(jid) || !text || text.length > MAX_MESSAGE_CHARS || !requestId || requestId.length > MAX_REQUEST_ID_CHARS) {
    writeJson(res, 422, { status: "invalid", error: "invalid_message_request" });
    return;
  }
  const result = await outbound.run(requestId, jid, text, async () => {
    state.logf(`outbound start request=${requestId} target=${jid} text_len=${text.length}`);
    try {
      const providerMessageId = await bridge.sendText(jid, text);
      state.logf(`outbound ack request=${requestId} provider=${providerMessageId} target=${jid}`);
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
  const httpStatus = result.status === "sent" ? 200 : 503;
  writeJson(res, httpStatus, result);
}

function setupPageHtml() {
  const s = state.snapshot();
  let pairing = "<p>Tidak ada QR aktif.</p>";
  if (s.connection === "connected") {
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
  const refresh = s.connection !== "connected" && s.connection !== "pairing-required" ? '<meta http-equiv="refresh" content="5">' : "";
  const rows =
    s.groups
      .map((g) => `<tr><td>${escapeHtml(g.subject)}</td><td><code>${escapeHtml(g.jid)}</code></td></tr>`)
      .join("") || `<tr><td colspan="2">Belum ada grup terbaca.</td></tr>`;
  return (
    `<!doctype html><html lang="id"><head><meta charset="utf-8">${refresh}` +
    `<meta name="viewport" content="width=device-width,initial-scale=1"><title>Setup BAST Bot (prototype)</title>` +
    `<style>body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:52rem;padding:0 1rem;line-height:1.5}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}pre{background:#f5f5f5;padding:.75rem;overflow:auto;max-height:18rem}.status{font-weight:600}.warn{background:#fff3cd;padding:.75rem;border-radius:.25rem}</style>` +
    `</head><body><div class="warn">PROTOTYPE -- whatsapp-web.js transport. Not wired into production. Pair only a TEST number here.</div>` +
    `<h1>Setup BAST Bot -- whatsapp-web.js (prototype)</h1>` +
    `<p class="status">Status: ${escapeHtml(s.connection)} -- ready=${bridge.isReady()} -- ${escapeHtml(s.me)}</p>` +
    `<h2>1. Pairing WhatsApp</h2>${pairing}` +
    `<h2>2. Grup terbaca (semua grup yang di-join, tidak ada allowlist)</h2><table><thead><tr><th>Nama grup</th><th>JID</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<h2>Log</h2><pre>${escapeHtml(s.logs.join("\n"))}</pre></body></html>`
  );
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      writeJson(res, 200, { alive: true, ready: bridge.isReady(), connection: state.connection, me: state.me, transport: "whatsapp-web.js" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/ready") {
      const ready = bridge.isReady();
      writeJson(res, ready ? 200 : 503, {
        ready,
        connection: state.connection,
        operatorActionRequired: state.operatorActionRequired,
        operatorReason: nullable(state.operatorReason),
        transport: "whatsapp-web.js",
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/internal/v1/status") {
      await handleStatus(req, res);
      return;
    }
    if (req.method === "POST" && url.pathname === "/internal/v1/messages") {
      await handleSendOutbound(req, res);
      return;
    }
    if (req.method === "POST" && url.pathname === "/pair") {
      // whatsapp-web.js has no explicit "begin pairing" call the way the Go
      // bridge does: initialize() itself emits `qr`. If we're latched on
      // operatorActionRequired, clear the latch and re-initialize.
      if (state.operatorActionRequired) {
        state.clearOperatorAction();
        state.logf("operator explicitly requested WhatsApp pairing");
        bridge.start().catch((err) => state.logf(`pairing restart failed: ${err.message}`));
      }
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

if (state.operatorActionRequired) {
  state.setConnection("pairing-required");
  state.logf(`automatic pairing blocked after permanent disconnect; explicit operator action required: ${state.operatorReason}`);
} else {
  bridge.start().catch((err) => {
    state.setConnection("failed");
    state.logf(`initialize failed: ${err.stack || err}`);
  });
}

process.on("SIGTERM", async () => {
  state.logf("shutdown requested");
  await bridge.client.destroy().catch(() => {});
  server.close(() => process.exit(0));
});
