"use strict";

// WhatsApp session holder for the Digital BAST bot.
// It owns ONLY transport concerns: pair the number, keep the socket alive,
// receive messages, and hand each one to bot-worker over HTTP for the actual
// business reply. Deliberately has no `digital-bast` CLI/business logic of
// its own and is not built FROM the app image, so it never rebuilds just
// because the app changed -- see docs/bast-bot.md and the split's plan for
// why: recreating this container drops the live WhatsApp connection, and
// WhatsApp's own anti-abuse system revokes the session after a few rapid
// reconnects, which is exactly what coupling this to every app deploy caused.

const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");
const QRCode = require("qrcode");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  downloadMediaMessage,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");
const { ownUserIds, isForUs, looksLikeConversation, looksLikeDmFastPath } = require("./mention");
const { waitingReply } = require("./greeting");
const { handleOutboundRequest, safeEqual, configuredToken } = require("./outbound");

const AUTH_DIR = process.env.BOT_AUTH_DIR || path.join(__dirname, "auth");
const DATA_DIR = process.env.BOT_DATA_DIR || path.join(__dirname, "data");
const EVIDENCE_DIR = path.join(DATA_DIR, "evidence-uploads");
const CONFIG_FILE = path.join(DATA_DIR, "config.json");
const PORT = Number(process.env.BOT_SETUP_PORT || 8090);
const HOST = process.env.BOT_SETUP_HOST || "127.0.0.1";
const BOT_WORKER_BASE_URL = process.env.BOT_WORKER_BASE_URL || "http://bot-worker:8091";
const EVIDENCE_UPLOAD_IN_GROUP_REPLY =
  "Upload evidence-nya lewat chat pribadi ke aku ya, bukan di grup 🙏 " +
  "Tinggal kirim foto/dokumennya langsung ke DM aku.";

const state = {
  connection: "starting",
  qrDataUrl: "",
  pairingCode: "",
  me: "",
  groups: [],
  log: [],
  socket: null,
};

// Alternative to QR: WhatsApp's own "Link with phone number instead" screen,
// which needs a code we request FROM Baileys (not scan a QR) -- lets a
// phone-only user re-pair without a second screen/device to point a camera
// at. Only meaningful before a session exists (Baileys errors if requested
// against an already-registered session), and requires the bot's own number
// in international format, digits only (e.g. "62881080735871").
const PAIRING_NUMBER = (process.env.BOT_PAIRING_NUMBER || "").replace(/[^0-9]/g, "");

function log(line) {
  const entry = `${new Date().toISOString()} ${line}`;
  state.log.unshift(entry);
  state.log = state.log.slice(0, 40);
  console.log(entry);
}

process.on("uncaughtException", (error) => {
  log(`uncaughtException (bot stays up): ${error && error.stack ? error.stack : error}`);
});
process.on("unhandledRejection", (reason) => {
  log(`unhandledRejection (bot stays up): ${reason && reason.stack ? reason.stack : reason}`);
});

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
  } catch {
    return { allowedGroups: [] };
  }
}

function writeConfig(config) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
}

function allowedGroups() {
  const fromEnv = (process.env.BOT_ALLOWED_GROUPS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return new Set([...fromEnv, ...readConfig().allowedGroups]);
}

function messageText(message) {
  const content = message.message || {};
  return (
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    content.documentMessage?.caption ||
    ""
  );
}

// bot-worker holds no WhatsApp state, so recreating it (every deploy, like
// today's combined bridge used to) never touches this process's live socket.
async function callBotWorker(payload) {
  try {
    const response = await fetch(`${BOT_WORKER_BASE_URL}/internal/v1/reply`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-bridge-token": configuredToken() },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    if (!data || typeof data.ok !== "boolean") {
      return { ok: false, text: `bot-worker returned an unexpected response (HTTP ${response.status})` };
    }
    return data;
  } catch (error) {
    return { ok: false, text: `bot-worker unreachable: ${error}` };
  }
}

function requestId() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function friendlyErrorReply(context, resultText) {
  const id = requestId();
  log(`${context} failed [${id}]: ${resultText}`);
  return (
    `Maaf, proses gagal saat ${context}.\n` +
    `Coba lagi beberapa saat atau hubungi admin jika tetap gagal. (ref: ${id})`
  );
}

function parseFileReply(text) {
  try {
    const parsed = JSON.parse(text);
    return parsed && parsed.kind === "file" && parsed.path ? parsed : null;
  } catch {
    return null;
  }
}

const MIME_BY_EXTENSION = {
  ".pdf": "application/pdf",
  ".csv": "text/csv",
  ".png": "image/png",
};

function mimetypeFor(filePath) {
  return MIME_BY_EXTENSION[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

async function sendFileReply(sock, jid, message, filePayload) {
  try {
    const buffer = fs.readFileSync(filePayload.path);
    const mimetype = mimetypeFor(filePayload.path);
    const payload = mimetype.startsWith("image/")
      ? { image: buffer, caption: filePayload.caption || "" }
      : {
          document: buffer,
          fileName: filePayload.filename || path.basename(filePayload.path),
          mimetype,
          caption: filePayload.caption || "",
        };
    await sock.sendMessage(jid, payload, { quoted: message });
    fs.unlink(filePayload.path, (error) => {
      if (error) log(`export cleanup failed: ${error}`);
    });
  } catch (error) {
    await sock.sendMessage(
      jid,
      { text: friendlyErrorReply("mengirim berkas", String(error)) },
      { quoted: message },
    );
  }
}

async function refreshGroups(sock) {
  try {
    const groups = await sock.groupFetchAllParticipating();
    state.groups = Object.values(groups).map((group) => ({
      jid: group.id,
      subject: group.subject || group.id,
    }));
  } catch (error) {
    log(`group list unavailable: ${error}`);
  }
}

async function start() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  const sock = makeWASocket({
    version,
    auth,
    printQRInTerminal: false,
    syncFullHistory: false,
    browser: ["Digital BAST Bot", "Chrome", "1.0.0"],
  });
  state.socket = sock;

  if (PAIRING_NUMBER && !auth.creds.registered) {
    // makeWASocket() returns before the underlying websocket actually opens
    // -- requesting a pairing code immediately races the handshake and
    // fails with "Connection Closed". A short delay lets it connect first.
    setTimeout(async () => {
      try {
        state.pairingCode = await sock.requestPairingCode(PAIRING_NUMBER);
        log(`pairing code issued for ${PAIRING_NUMBER}; enter it on WhatsApp > Link with phone number`);
      } catch (error) {
        log(`pairing code request failed: ${error}`);
      }
    }, 3000);
  }

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      state.qrDataUrl = await QRCode.toDataURL(qr, { margin: 1, width: 320 });
      state.connection = "awaiting-scan";
      log("QR refreshed; open the setup page and scan it");
    }
    if (connection === "open") {
      state.connection = "connected";
      state.qrDataUrl = "";
      state.pairingCode = "";
      state.me = sock.user?.id || "";
      state.socket = sock;
      log(`connected as ${state.me}`);
      await refreshGroups(sock);
    }
    if (connection === "close") {
      const status = lastDisconnect?.error?.output?.statusCode;
      state.connection = "disconnected";
      if (state.socket === sock) state.socket = null;
      log(`connection closed (${status ?? "unknown"})`);
      if (status === DisconnectReason.loggedOut) {
        log("logged out; delete the auth directory and scan again");
        return;
      }
      setTimeout(() => {
        start().catch((error) => log(`restart failed: ${error}`));
      }, 3000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const message of messages) {
      const jid = message.key?.remoteJid || "";
      if (message.key?.fromMe || !jid) continue;
      if (jid.endsWith("@g.us")) {
        await handleGroupMessage(sock, message, jid);
      } else if (jid.endsWith("@s.whatsapp.net") || jid.endsWith("@lid")) {
        await handleDirectMessage(sock, message, jid);
      }
    }
  });

  return sock;
}

async function handleGroupMessage(sock, message, jid) {
  const text = messageText(message);
  const content = message.message || {};
  const media = content.imageMessage || content.documentMessage;
  const forUs = isForUs(message, text, ownUserIds(sock));
  if (media && forUs) {
    if (!allowedGroups().has(jid)) {
      log(`ignored message from unlisted group ${jid}`);
      return;
    }
    log(`evidence-in-group redirect for ${jid}`);
    await sock.sendMessage(jid, { text: EVIDENCE_UPLOAD_IN_GROUP_REPLY }, { quoted: message });
    return;
  }
  if (!text || !forUs) return;
  if (!allowedGroups().has(jid)) {
    log(`ignored message from unlisted group ${jid}`);
    return;
  }
  log(`command from ${jid}: ${text.slice(0, 120)}`);
  if (!looksLikeConversation(text)) {
    await sock.sendMessage(
      jid,
      { text: waitingReply(message.pushName) },
      { quoted: message },
    );
  }
  const startedAt = Date.now();
  const result = await callBotWorker({ kind: "text", text });
  const elapsed = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
  const filePayload = result.ok ? parseFileReply(result.text) : null;
  if (filePayload) {
    filePayload.caption = `${filePayload.caption || ""} (${elapsed})`.trim();
    await sendFileReply(sock, jid, message, filePayload);
    return;
  }
  const reply = result.ok
    ? `${result.text}\n\n_${elapsed}_`
    : friendlyErrorReply("menjalankan perintah", result.text);
  await sock.sendMessage(jid, { text: reply || "(kosong)" }, { quoted: message });
}

async function handleDirectMessage(sock, message, jid) {
  const content = message.message || {};
  const media = content.imageMessage || content.documentMessage;
  if (media) {
    await handleEvidenceUpload(sock, message, jid, media);
    return;
  }
  const text = messageText(message);
  if (!text) return;
  log(`dm from ${jid}: ${text.slice(0, 120)}`);
  if (!looksLikeDmFastPath(text)) {
    await sock.sendMessage(jid, { text: waitingReply(message.pushName) }, { quoted: message });
  }
  const result = await callBotWorker({ kind: "text", text, jid, channel: "dm" });
  const reply = result.ok
    ? result.text
    : friendlyErrorReply("menjalankan perintah", result.text);
  await sock.sendMessage(jid, { text: reply || "(kosong)" }, { quoted: message });
}

function evidenceFileExtension(mimetype) {
  if (mimetype && mimetype.includes("png")) return "png";
  if (mimetype && mimetype.includes("webp")) return "webp";
  return "jpg";
}

async function handleEvidenceUpload(sock, message, jid, media) {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  const caption = media.caption || "";
  const extension = evidenceFileExtension(media.mimetype);
  const filePath = path.join(
    EVIDENCE_DIR,
    `${Date.now()}-${Math.random().toString(36).slice(2)}.${extension}`,
  );
  try {
    const buffer = await downloadMediaMessage(
      message,
      "buffer",
      {},
      { logger: console, reuploadRequest: sock.updateMediaMessage },
    );
    fs.writeFileSync(filePath, buffer);
    log(`evidence upload from ${jid} (${buffer.length} bytes)`);
    const result = await callBotWorker({ kind: "evidence", jid, filePath, caption });
    const reply = result.ok
      ? result.text
      : friendlyErrorReply("menyimpan evidence", result.text);
    await sock.sendMessage(jid, { text: reply || "(kosong)" }, { quoted: message });
  } catch (error) {
    await sock.sendMessage(
      jid,
      { text: friendlyErrorReply("mengunduh foto/dokumen", String(error)) },
      { quoted: message },
    );
  } finally {
    fs.unlink(filePath, () => {});
  }
}

function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
}

function page() {
  const allowed = allowedGroups();
  const refresh = state.connection === "connected" ? "" : '<meta http-equiv="refresh" content="5">';
  const qr = state.qrDataUrl
    ? `<img alt="WhatsApp QR" src="${state.qrDataUrl}" width="320" height="320">`
    : "<p>Tidak ada QR aktif.</p>";
  const pairingCode = state.pairingCode
    ? `<p>Atau masukkan kode ini di WhatsApp &gt; Tautkan dengan nomor telepon: <strong>${escapeHtml(state.pairingCode)}</strong></p>`
    : "";
  const groups = state.groups.length
    ? state.groups
        .map(
          (group) =>
            `<tr><td><input type="checkbox" name="jid" value="${escapeHtml(group.jid)}" ${
              allowed.has(group.jid) ? "checked" : ""
            }></td><td>${escapeHtml(group.subject)}</td><td><code>${escapeHtml(
              group.jid,
            )}</code></td></tr>`,
        )
        .join("")
    : '<tr><td colspan="3">Belum ada grup terbaca. Pastikan bot sudah diundang ke grup.</td></tr>';
  return `<!doctype html>
<html lang="id"><head><meta charset="utf-8">${refresh}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Setup BAST Bot</title>
<style>
 body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:52rem;padding:0 1rem;line-height:1.5}
 table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}
 code{font-size:.85em}pre{background:#f5f5f5;padding:.75rem;overflow:auto;max-height:16rem}
 .status{font-weight:600}
</style></head><body>
<h1>Setup BAST Bot</h1>
<p class="status">Status: ${escapeHtml(state.connection)}${
    state.me ? ` — ${escapeHtml(state.me)}` : ""
  }</p>
<h2>1. Pairing WhatsApp</h2>
${state.connection === "connected" ? "<p>Sudah terhubung. Tidak perlu scan lagi.</p>" : `${qr}${pairingCode}`}
<h2>2. Grup yang diizinkan</h2>
<form method="post" action="/allow">
<table><thead><tr><th>Aktif</th><th>Nama grup</th><th>JID</th></tr></thead><tbody>${groups}</tbody></table>
<p><button type="submit">Simpan</button></p>
</form>
<h2>3. Uji perintah</h2>
<form method="post" action="/try">
<p><input name="text" size="60" value="@BAST Bot system status"> <button type="submit">Jalankan</button></p>
</form>
<h2>Log</h2>
<pre>${escapeHtml(state.log.join("\n"))}</pre>
</body></html>`;
}

function readBody(request) {
  return new Promise((resolve) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > 64 * 1024) request.destroy();
    });
    request.on("end", () => resolve(new URLSearchParams(body)));
  });
}

const server = http.createServer(async (request, response) => {
  if (await handleOutboundRequest(request, response, state, log)) return;

  const url = new URL(request.url, `http://${request.headers.host}`);
  if (request.method === "GET" && url.pathname === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ connection: state.connection, me: state.me }));
    return;
  }
  // Narrow, read-only mirror of the setup page's QR/status for TalentOps
  // (System & sync) to proxy in -- never exposes /allow or /try, which have
  // no auth of their own and must stay loopback-only.
  if (request.method === "GET" && url.pathname === "/internal/v1/status") {
    const expected = configuredToken();
    const supplied = request.headers["x-bridge-token"];
    if (!expected || !safeEqual(supplied, expected)) {
      response.writeHead(403, { "content-type": "application/json" });
      response.end(JSON.stringify({ status: "forbidden" }));
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        connection: state.connection,
        me: state.me,
        qrDataUrl: state.qrDataUrl || null,
        pairingCode: state.pairingCode || null,
      }),
    );
    return;
  }
  if (request.method === "POST" && url.pathname === "/allow") {
    const body = await readBody(request);
    writeConfig({ allowedGroups: body.getAll("jid") });
    log(`allowlist updated (${body.getAll("jid").length} grup)`);
    response.writeHead(303, { location: "/" });
    response.end();
    return;
  }
  if (request.method === "POST" && url.pathname === "/try") {
    const body = await readBody(request);
    const result = await callBotWorker({ kind: "text", text: body.get("text") || "" });
    response.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
    response.end(result.text || "(kosong)");
    return;
  }
  if (request.method === "GET" && url.pathname === "/") {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(page());
    return;
  }
  response.writeHead(404, { "content-type": "text/plain" });
  response.end("not found");
});

server.listen(PORT, HOST, () => {
  log(`setup page on http://${HOST}:${PORT}`);
});

start().catch((error) => {
  log(`startup failed: ${error}`);
  state.connection = "failed";
  state.socket = null;
});