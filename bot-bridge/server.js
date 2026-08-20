"use strict";

// WhatsApp bridge for the Digital BAST bot.
// It owns exactly three jobs: pair the number, listen in allowlisted groups,
// and hand the raw message to `digital-bast bot-reply`. No business logic here.

const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");
const { execFile } = require("node:child_process");
const QRCode = require("qrcode");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  downloadMediaMessage,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");
const { ownUserIds, isForUs, looksLikeConversation } = require("./mention");
const { waitingReply } = require("./greeting");

const ROOT = path.resolve(__dirname, "..");
const AUTH_DIR = process.env.BOT_AUTH_DIR || path.join(__dirname, "auth");
const DATA_DIR = process.env.BOT_DATA_DIR || path.join(__dirname, "data");
const EVIDENCE_DIR = path.join(DATA_DIR, "evidence-uploads");
const CONFIG_FILE = path.join(DATA_DIR, "config.json");
const PORT = Number(process.env.BOT_SETUP_PORT || 8090);
const HOST = process.env.BOT_SETUP_HOST || "127.0.0.1";
const CLI = (process.env.BAST_CLI || "digital-bast").split(" ").filter(Boolean);
const CLI_TIMEOUT_MS = Number(process.env.BAST_CLI_TIMEOUT_MS || 180000);

const state = {
  connection: "starting",
  qrDataUrl: "",
  me: "",
  groups: [],
  log: [],
};

function log(line) {
  const entry = `${new Date().toISOString()} ${line}`;
  state.log.unshift(entry);
  state.log = state.log.slice(0, 40);
  console.log(entry);
}

// Baileys throws (not just rejects) from deep inside its own send/query
// internals on a transient socket state -- e.g. "Connection Closed" while a
// reconnect is in flight (see groupMetadata -> sendNode -> sendRawMessage).
// Node's default behavior for an uncaught exception/rejection is to crash
// the whole process, which took the bot offline outright. Log and keep
// running instead -- a single failed send/query should not end the session;
// Baileys' own reconnect logic (connection.update handler below) recovers
// the socket on its own.
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
    ""
  );
}

function runCli(args) {
  return new Promise((resolve) => {
    execFile(
      CLI[0],
      [...CLI.slice(1), ...args],
      { cwd: ROOT, timeout: CLI_TIMEOUT_MS, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, text: (stderr || stdout || String(error)).trim() });
          return;
        }
        resolve({ ok: true, text: stdout.trim() });
      },
    );
  });
}

function requestId() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

// The full stdout/stderr/traceback from a failed CLI call goes to the
// process log only -- WhatsApp gets a short Indonesian message plus a
// ref id so the two can be correlated without ever putting a filesystem
// path, Python traceback, or SQL detail in front of the sender.
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
    // The status-matrix PNG (cli.py generate-status-matrix) is meant to be
    // read inline in the chat, not saved -- everything else (CSV/PDF export)
    // stays a document attachment.
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
      state.me = sock.user?.id || "";
      log(`connected as ${state.me}`);
      await refreshGroups(sock);
    }
    if (connection === "close") {
      const status = lastDisconnect?.error?.output?.statusCode;
      state.connection = "disconnected";
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
        // A 1:1 chat's remoteJid is the phone-number JID or the privacy "@lid"
        // JID depending on the *other* side's addressing mode (same ambiguity
        // as group mentions, see mention.js) -- @lid alone used to fall through
        // neither branch and get silently dropped.
        await handleDirectMessage(sock, message, jid);
      }
    }
  });

  return sock;
}

// GROUP: monitoring + commands, unchanged -- mention-gated, allowlist-gated.
async function handleGroupMessage(sock, message, jid) {
  const text = messageText(message);
  if (!text || !isForUs(message, text, ownUserIds(sock))) return;
  if (!allowedGroups().has(jid)) {
    log(`ignored message from unlisted group ${jid}`);
    return;
  }
  log(`command from ${jid}: ${text.slice(0, 120)}`);
  // A plain greeting/intro (see mention.js::looksLikeConversation, mirrors
  // cli.py's conversation fast-path) doesn't need a "this'll take a
  // moment" heads-up -- generate/export/status and everything else still
  // gets it immediately, same as before.
  if (!looksLikeConversation(text)) {
    await sock.sendMessage(
      jid,
      { text: waitingReply(message.pushName) },
      { quoted: message },
    );
  }
  const startedAt = Date.now();
  const result = await runCli(["bot-reply", "--text", text]);
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

// DM: activation + evidence only. No trigger word needed -- every DM is in scope,
// and digital-bast itself enforces "unbound JID can only attempt activation"
// (see cli.py::_dm_reply). No business logic here, same rule as the group path.
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
  const result = await runCli(["bot-reply", "--text", text, "--jid", jid, "--channel", "dm"]);
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

// WhatsApp re-compresses photos sent as imageMessage; documentMessage preserves
// the original bytes. Both are accepted -- digital-bast bot-evidence sniffs
// magic bytes and validates size/type itself, so the bridge just downloads and
// hands off the file.
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
    const result = await runCli([
      "bot-evidence",
      "--jid",
      jid,
      "--file",
      filePath,
      "--caption",
      caption,
    ]);
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
${state.connection === "connected" ? "<p>Sudah terhubung. Tidak perlu scan lagi.</p>" : qr}
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
  const url = new URL(request.url, `http://${request.headers.host}`);
  if (request.method === "GET" && url.pathname === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ connection: state.connection, me: state.me }));
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
    const result = await runCli(["bot-reply", "--text", body.get("text") || ""]);
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
});
