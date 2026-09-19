"use strict";

// whatsapp-web.js transport. Structure deliberately mirrors
// whatsmeow-session/bridge.go so the two are easy to diff behavior-for-
// behavior; see the migration doc for the full contract this replaces.
//
// PROTOTYPE STATUS (read before trusting this against real traffic):
// - Group/DM trigger matching, menu shortcuts, interactive/file reply
//   envelopes, wait-notice and quoting are ported from the Go bridge.
// - Evidence-in-group redirect and evidence download/forward are ported.
// - NOT yet validated against real WhatsApp traffic: whether whatsapp-web.js
//   ever exposes a group-participant "LID" distinct from the phone-number
//   JID the way whatsmeow's canonicalDMIdentity() has to handle. This
//   prototype uses `message.author || message.from` as the identity JID and
//   `message.from` as the transport JID, unverified. Confirm empirically
//   during pairing against a real (test) account before relying on it for
//   per-JID menu state or worker `jid` values.
// - Pairing-code (BOT_PAIRING_NUMBER): confirmed present in whatsapp-web.js
//   1.26.0 (Client.prototype.requestPairingCode(phoneNumber, showNotification)
//   -- inspected the installed package source directly, not assumed from
//   docs, since this API has moved across versions historically). Wired up
//   below, same env var name and "digits-only, only takes effect while
//   unregistered" contract as whatsmeow-session's BOT_PAIRING_NUMBER.

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { Client, LocalAuth } = require("whatsapp-web.js");
const QRCode = require("qrcode");

const {
  GROUP_TRIGGER,
  looksLikeConversation,
  looksLikeDMFastPath,
  waitingReply,
  friendlyError,
  parseInteractiveReply,
  fallbackText,
  parseFileReply,
  MenuStore,
} = require("./helpers");

// See README.md "Known issue": WhatsApp Web renamed _serialized to $1 on
// some id-like objects on this build; used for trace-id logging everywhere
// below so log lines don't read "in=undefined".
function msgId(msg) {
  return msg?.id?._serialized ?? msg?.id?.$1 ?? "?";
}

const EVIDENCE_IN_GROUP_REPLY =
  "Upload evidence-nya lewat chat pribadi ke aku ya, bukan di grup \u{1F64F} Tinggal kirim foto/dokumennya langsung ke DM aku.";

class Bridge {
  constructor({ state, authDir, dataDir, workerBaseUrl, bridgeToken, waitNoticeDelayMs }) {
    this.state = state;
    this.dataDir = dataDir;
    this.workerBaseUrl = workerBaseUrl.replace(/\/+$/, "");
    this.bridgeToken = bridgeToken;
    this.waitDelay = waitNoticeDelayMs;
    this.menus = new MenuStore();

    this.client = new Client({
      authStrategy: new LocalAuth({ dataPath: authDir }),
      // Default is LocalWebCache, which writes a version HTML file under a
      // *relative* path ("./.wwebjs_cache/") -- incompatible with this
      // container's read_only rootfs (see README.md "Known issue": this
      // silently failed with ENOENT inside a fire-and-forget browser-side
      // call, so it never surfaced as a Node-side error or log line, and
      // was the actual reason `ready` never fired despite every other fix).
      // We always want the live version anyway, so skip caching entirely.
      webVersionCache: { type: "none" },
      puppeteer: {
        headless: true,
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
        args: [
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage",
          "--disable-gpu",
        ],
      },
    });

    this._pairingNumber = String(process.env.BOT_PAIRING_NUMBER || "").replace(/\D/g, "");
    this._pairingRequested = false;

    this._wireEvents();
  }

  async start() {
    this._pairingRequested = false;
    this.state.logf("initializing whatsapp-web.js client");
    await this.client.initialize();
  }

  _wireEvents() {
    const { client, state } = this;

    client.on("qr", async (qr) => {
      try {
        state.qrDataUrl = await QRCode.toDataURL(qr, { width: 320 });
      } catch (err) {
        state.logf(`qr render failed: ${err.message}`);
      }
      state.setConnection("awaiting-scan");
      state.logf("pairing QR refreshed");
      // Mirrors whatsmeow-session/main.go: request the code once per
      // pairing attempt, only while unregistered -- a no-op once paired
      // (the `qr` event stops firing after a successful scan/code entry).
      if (this._pairingNumber && !this._pairingRequested) {
        this._pairingRequested = true;
        try {
          const code = await this.client.requestPairingCode(this._pairingNumber, true);
          state.pairingCode = code;
          state.logf("pairing code issued for configured phone");
        } catch (err) {
          state.logf(`pairing code request failed: ${err.message}`);
        }
      }
    });

    client.on("authenticated", () => {
      state.qrDataUrl = "";
      state.pairingCode = "";
      this._pairingRequested = false;
      state.logf("pairing successful; waiting for authenticated connection");
    });

    client.on("error", (err) => {
      state.logf(`whatsapp-web.js client error: ${err && err.stack ? err.stack : err}`);
    });

    client.on("auth_failure", (msg) => {
      state.requireOperatorAction("auth-failure", String(msg));
      state.logf(`whatsapp-web.js auth failure; operator action required: ${msg}`);
    });

    client.on("loading_screen", (percent, message) => {
      state.logf(`whatsapp-web.js loading_screen ${percent}% ${message}`);
    });

    client.on("change_state", (newState) => {
      state.logf(`whatsapp-web.js change_state ${newState}`);
    });

    client.on("ready", () => {
      state.setConnection("connected");
      state.clearOperatorAction();
      state.me = client.info?.wid?._serialized || "";
      state.logf(`whatsapp-web.js connected as ${state.me}`);
      this._refreshGroups().catch((err) => state.logf(`group list unavailable: ${err.message}`));
    });

    client.on("disconnected", (reason) => {
      // whatsapp-web.js's own `disconnected` fires for both transient
      // socket drops and a real logout; it does NOT auto re-initialize the
      // client itself (unlike whatsmeow's built-in reconnect), so on a
      // "LOGOUT" reason specifically we latch operatorActionRequired the
      // same way the Go bridge does for events.LoggedOut. Any other reason
      // is logged but left for the operator to decide whether to restart
      // the process -- do NOT loop client.initialize() here.
      if (String(reason).toUpperCase() === "LOGOUT") {
        state.requireOperatorAction("logged-out", String(reason));
        state.logf(`whatsapp-web.js permanent logout; automatic re-pair blocked`);
      } else {
        state.setConnection("disconnected");
        state.logf(`whatsapp-web.js disconnected: ${reason}`);
      }
    });

    client.on("message", (msg) => {
      this._handleMessage(msg).catch((err) => state.logf(`message handling failed: ${err.stack || err}`));
    });
  }

  async _refreshGroups() {
    const chats = await this.client.getChats();
    this.state.groups = chats
      .filter((c) => c.isGroup)
      .map((c) => ({ jid: c.id._serialized, subject: c.name || "" }));
  }

  isReady() {
    return this.state.connection === "connected" && !this.state.operatorActionRequired;
  }

  async callWorker(payload) {
    const url = `${this.workerBaseUrl}/internal/v1/reply`;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json", "x-bridge-token": this.bridgeToken },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(90_000),
      });
      const json = await res.json();
      return { ok: Boolean(json.ok), text: String(json.text ?? "") };
    } catch (err) {
      this.state.logf(`callWorker: fetch threw: ${err.stack || err}`);
      return { ok: false, text: `bot-worker unreachable: ${err.message}` };
    }
  }

  async callWorkerWithNotice(msg, payload, delayed) {
    if (!delayed) return this.callWorker(payload);
    const promise = this.callWorker(payload);
    const timeout = new Promise((resolve) => setTimeout(() => resolve("__timeout__"), this.waitDelay));
    const first = await Promise.race([promise, timeout]);
    if (first !== "__timeout__") return first;
    this.state.logf(`worker wait-notice in=${msgId(msg)}`);
    await this._reply(msg, waitingReply(msg._data?.notifyName || ""));
    return promise;
  }

  async _reply(msg, text) {
    try {
      await msg.reply(text);
      this.state.logf(`reply sent in=${msgId(msg)}`);
    } catch (err) {
      this.state.logf(`send reply failed in=${msgId(msg)}: ${err.message}`);
    }
  }

  async _sendWorkerReply(msg, menuKey, result, errorContext) {
    this.menus.forget(menuKey);
    if (!result.ok) {
      await this._reply(msg, friendlyError((l) => this.state.logf(l), errorContext, result.text));
      return;
    }
    const interactive = parseInteractiveReply(result.text);
    if (interactive) {
      if (interactive.digitShortcuts) this.menus.remember(menuKey, interactive.actions);
      await this._reply(msg, fallbackText(interactive));
      return;
    }
    const file = parseFileReply(result.text);
    if (file) {
      try {
        await this._sendFile(msg, file);
        this._cleanupExport(file.path);
      } catch (err) {
        await this._reply(msg, friendlyError((l) => this.state.logf(l), "mengirim berkas", err.message));
      }
      return;
    }
    await this._reply(msg, result.text.trim() === "" ? "(kosong)" : result.text);
  }

  async _sendFile(msg, file) {
    const { MessageMedia } = require("whatsapp-web.js");
    const media = MessageMedia.fromFilePath(file.path);
    if (file.filename) media.filename = file.filename;
    await msg.reply(media, undefined, { caption: file.caption || "" });
  }

  _cleanupExport(filePath) {
    if (!filePath) return;
    fs.rm(filePath, { force: true }, (err) => {
      if (err) this.state.logf(`export cleanup failed for ${filePath}: ${err.message}`);
    });
  }

  async _handleMessage(msg) {
    if (msg.fromMe) return;
    // WhatsApp Status interactions (someone viewing/replying to this
    // number's Status) surface as inbound messages with `from ===
    // "status@broadcast"` -- confirmed live, 2026-09-04. These are not DMs;
    // treating them as one routes into sendMessage()'s isStatus branch on
    // reply, which calls a WAWebStatusGatingUtils function this WhatsApp
    // Web build doesn't have (window.require(...).canCheckStatusRankingPosterGating
    // is not a function). Not a business message either way -- skip.
    if (msg.from === "status@broadcast") {
      this.state.logf(`ignoring status@broadcast interaction in=${msgId(msg)}`);
      return;
    }
    const chat = await msg.getChat();
    if (chat.isGroup) {
      await this._handleGroup(msg, chat);
      return;
    }
    await this._handleDM(msg);
  }

  async _isForUs(msg, text) {
    const mentions = await msg.getMentions().catch(() => []);
    const me = this.client.info?.wid?._serialized;
    if (me && mentions.some((c) => c.id._serialized === me)) return true;
    return GROUP_TRIGGER.test(text);
  }

  async _handleGroup(msg, chat) {
    const text = msg.body || "";
    const forUs = await this._isForUs(msg, text);
    if (msg.hasMedia && forUs) {
      this.state.logf(`evidence-in-group redirect in=${msgId(msg)} group=${chat.id._serialized}`);
      await this._reply(msg, EVIDENCE_IN_GROUP_REPLY);
      return;
    }
    if (!text || !forUs) return;
    this.state.logf(`group command in=${msgId(msg)} group=${chat.id._serialized} text=${text.slice(0, 120)}`);
    const started = Date.now();
    const result = await this.callWorkerWithNotice(msg, { kind: "text", text }, !looksLikeConversation(text));
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    if (result.ok) {
      const file = parseFileReply(result.text);
      if (file) {
        if (file.caption) file.caption = `${file.caption} (${elapsed}s)`;
        try {
          await this._sendFile(msg, file);
          this._cleanupExport(file.path);
        } catch (err) {
          this.state.logf(`send group file failed in=${msgId(msg)}: ${err.message}`);
        }
        return;
      }
      await this._reply(msg, `${result.text}\n\n_${elapsed}s_`);
      return;
    }
    await this._reply(msg, friendlyError((l) => this.state.logf(l), "menjalankan perintah", result.text));
  }

  async _handleDM(msg) {
    if (msg.hasMedia) {
      await this._handleEvidence(msg);
      return;
    }
    const text = msg.body || "";
    if (!text) return;
    // See file header: unverified whether `author` ever differs from `from`
    // for a 1:1 chat the way whatsmeow's LID resolution has to handle.
    const identityJid = msg.author || msg.from;
    this.state.logf(`dm text in=${msgId(msg)} identity=${identityJid} text=${text.slice(0, 120)}`);
    const resolved = this.menus.resolve(identityJid, text);
    const result = await this.callWorkerWithNotice(
      msg,
      { kind: "text", text: resolved, jid: identityJid, channel: "dm" },
      !looksLikeDMFastPath(resolved),
    );
    await this._sendWorkerReply(msg, identityJid, result, "menjalankan perintah");
  }

  async _handleEvidence(msg) {
    const identityJid = msg.author || msg.from;
    let media;
    try {
      media = await msg.downloadMedia();
    } catch (err) {
      await this._reply(msg, friendlyError((l) => this.state.logf(l), "mengunduh foto/dokumen", err.message));
      return;
    }
    if (!media) {
      await this._reply(msg, friendlyError((l) => this.state.logf(l), "mengunduh foto/dokumen", "no media payload"));
      return;
    }
    const dir = path.join(this.dataDir, "evidence-uploads");
    fs.mkdirSync(dir, { recursive: true, mode: 0o750 });
    const ext = extensionForMime(media.mimetype);
    const filePath = path.join(dir, `evidence-${Date.now()}-${Math.random().toString(36).slice(2)}${ext}`);
    fs.writeFileSync(filePath, Buffer.from(media.data, "base64"), { mode: 0o640 });
    this.state.logf(`evidence upload in=${msgId(msg)} identity=${identityJid} bytes=${media.data.length}`);
    const result = await this.callWorker({
      kind: "evidence",
      jid: identityJid,
      filePath,
      caption: msg.body || "",
    });
    try {
      await this._sendWorkerReply(msg, identityJid, result, "menyimpan evidence");
    } finally {
      fs.rm(filePath, { force: true }, () => {});
    }
  }

  async sendText(jid, text) {
    const result = await this.client.sendMessage(jid, text);
    // See README.md "Known issue": WhatsApp Web renamed _serialized to $1 on
    // some id-like objects on this build; fall back rather than return "".
    return result?.id?._serialized || result?.id?.$1 || "";
  }
}

function extensionForMime(mimetype) {
  const mt = String(mimetype || "").toLowerCase();
  if (mt.includes("png")) return ".png";
  if (mt.includes("webp")) return ".webp";
  if (mt.includes("pdf")) return ".pdf";
  return ".jpg";
}

module.exports = { Bridge };
