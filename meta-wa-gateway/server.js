"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const { loadConfig, missingConfig } = require("./config");
const { GatewayDatabase } = require("./database");
const { MetaClient, MetaGraphError } = require("./meta-client");
const { webhookEvents, waIdToJid, jidToWaId } = require("./normalize");
const { parsedEnvelope, interactivePayload, extractUrl, fileEnvelope } = require("./replies");

const MAX_WEBHOOK_BYTES = 2 * 1024 * 1024;
const MAX_INTERNAL_BYTES = 64 * 1024;
const MAX_EVIDENCE_BYTES = 16 * 1024 * 1024;

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  return a.length > 0 && a.length === b.length && crypto.timingSafeEqual(a, b);
}

function validSignature(raw, signature, appSecret) {
  if (!signature?.startsWith("sha256=") || !appSecret) return false;
  const expected = `sha256=${crypto.createHmac("sha256", appSecret).update(raw).digest("hex")}`;
  return safeEqual(signature, expected);
}

function readBody(request, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("body_too_large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks)));
    request.on("error", reject);
  });
}

function json(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(payload));
}

function extensionFor(mimeType, mediaType) {
  const known = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
  };
  return known[mimeType] || (mediaType === "image" ? ".jpg" : ".bin");
}

class Gateway {
  constructor(config, { meta = null, database = null, fetchImpl = fetch, logger = console } = {}) {
    this.config = config;
    this.fetch = fetchImpl;
    this.meta = meta || new MetaClient(config, fetchImpl);
    this.database = database || new GatewayDatabase(config.databaseDsn);
    this.logger = logger;
    this.active = new Set();
  }

  async callWorker(payload) {
    const response = await this.fetch(`${this.config.workerBaseUrl}/internal/v1/reply`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-bridge-token": this.config.bridgeToken },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(180000),
    });
    const result = await response.json().catch(() => ({ ok: false, text: `worker_http_${response.status}` }));
    if (!response.ok || !result.ok) throw new Error(String(result.text || `worker_http_${response.status}`));
    return result;
  }

  async sendWorkerReply(message, result) {
    const envelope = parsedEnvelope(result.text);
    const interactive = envelope?.kind === "interactive" ? interactivePayload(envelope) : null;
    if (interactive) return this.meta.sendInteractive(message.waId, interactive, message.id);
    const file = fileEnvelope(envelope);
    if (file) {
      const relative = path.relative(path.resolve(this.config.dataDir), file.path);
      if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("worker_file_outside_data_dir");
      const id = await this.meta.sendFile(message.waId, file, message.id);
      fs.unlinkSync(file.path);
      return id;
    }
    const cta = extractUrl(result.text);
    if (cta) return this.meta.sendCtaUrl(message.waId, cta.text, cta.url, message.id);
    return this.meta.sendText(message.waId, result.text || "(kosong)", message.id);
  }

  async evidenceFile(message) {
    const media = await this.meta.downloadMedia(message.mediaId);
    if (media.buffer.length > MAX_EVIDENCE_BYTES) throw new Error("evidence_too_large");
    const dir = path.join(this.config.dataDir, "evidence-uploads");
    fs.mkdirSync(dir, { recursive: true });
    const extension = extensionFor(message.mimeType || media.mimeType, message.mediaType);
    const safeName = `${message.id.replace(/[^a-zA-Z0-9_-]/g, "_")}${extension}`;
    const filePath = path.join(dir, safeName);
    fs.writeFileSync(filePath, media.buffer, { mode: 0o600 });
    return filePath;
  }

  async processMessage(message) {
    if (!(await this.database.claimInbound(message))) return;
    let evidencePath = null;
    try {
      await this.meta.markRead(message.id).catch(() => null);
      if (message.kind === "unsupported") {
        await this.meta.sendText(
          message.waId,
          "Saat ini Digital BAST menerima pesan teks, pilihan menu, foto, dan dokumen.",
          message.id,
        );
      } else {
        let payload;
        if (message.kind === "evidence") {
          evidencePath = await this.evidenceFile(message);
          payload = {
            kind: "evidence",
            jid: waIdToJid(message.waId),
            filePath: evidencePath,
            caption: message.caption,
            providerMessageId: message.id,
          };
        } else {
          payload = {
            kind: "text",
            text: message.text,
            jid: waIdToJid(message.waId),
            channel: "dm",
            providerMessageId: message.id,
          };
        }
        const result = await this.callWorker(payload);
        await this.sendWorkerReply(message, result);
      }
      await this.database.completeInbound(message.id);
    } catch (error) {
      await this.database.failInbound(message.id, error.message || error).catch(() => null);
      this.logger.error(`Meta inbound failed id=${message.id}:`, error);
    } finally {
      if (evidencePath) fs.rmSync(evidencePath, { force: true });
    }
  }

  async processWebhook(payload) {
    const events = webhookEvents(payload);
    await Promise.all(events.messages.map((message) => this.processMessage(message)));
  }

  async acceptWebhook(payload) {
    const events = webhookEvents(payload);
    await this.database.enqueueInbound(events.messages);
    await Promise.all(events.statuses.map((event) => this.database.recordStatus(event)));
    return events;
  }

  async recoverInbound() {
    const messages = await this.database.pendingInbound();
    await Promise.all(messages.map((message) => this.processMessage(message)));
  }

  startRecovery() {
    if (this.recoveryTimer) return;
    const recover = () => Promise.all([
      this.recoverInbound(),
      this.database.reconcileStatuses(),
    ]).catch((error) => this.logger.error("Meta recovery failed:", error));
    this.recoveryTimer = setInterval(recover, 30000);
    this.recoveryTimer.unref();
    void recover();
  }

  async close() {
    if (this.recoveryTimer) clearInterval(this.recoveryTimer);
    this.recoveryTimer = null;
    await this.idle();
    await this.database.close();
  }

  scheduleWebhook(payload) {
    const task = this.processWebhook(payload).catch((error) => this.logger.error("Meta webhook processing failed:", error));
    this.active.add(task);
    task.finally(() => this.active.delete(task));
  }

  async idle() {
    await Promise.allSettled([...this.active]);
  }

  async sendOutbound(payload) {
    const requestId = String(payload.request_id || "").trim();
    const recipient = jidToWaId(payload.recipient || payload.jid);
    const kind = String(payload.kind || "auto");
    if (!requestId || !recipient) throw Object.assign(new Error("invalid_message_request"), { status: 422 });
    const canonical = { ...payload, recipient, request_id: requestId };
    const claim = await this.database.claimOutbound(requestId, canonical);
    if (claim.action === "conflict") throw Object.assign(new Error("request_id_conflict"), { status: 409 });
    if (claim.action === "pending") throw Object.assign(new Error("request_in_progress"), { status: 409 });
    if (claim.action === "replay") return claim.providerMessageId;

    try {
      let messageId;
      // This endpoint is application-initiated (TalentOps, scheduled reminders,
      // and PMO outboxes), so its safe default is an approved utility template.
      // Replies to inbound user messages bypass this endpoint and stay free-form.
      if (kind === "template" || kind === "auto") {
        const template = String(payload.template || this.config.utilityTemplate || "");
        if (!template) throw Object.assign(new Error("template_not_configured"), { status: 422 });
        const parameters = Array.isArray(payload.parameters) ? payload.parameters : [String(payload.text || "")];
        messageId = await this.meta.sendTemplate(
          recipient,
          template,
          String(payload.language || this.config.templateLanguage),
          parameters,
        );
      } else {
        try {
          messageId = await this.meta.sendText(recipient, String(payload.text || ""));
        } catch (error) {
          // Free-form business-initiated messages outside Meta's customer-service
          // window fail with 131047. Use the approved utility template instead.
          if (!(error instanceof MetaGraphError) || String(error.code) !== "131047" || !this.config.utilityTemplate) {
            throw error;
          }
          messageId = await this.meta.sendTemplate(
            recipient,
            this.config.utilityTemplate,
            this.config.templateLanguage,
            [String(payload.text || "")],
          );
        }
      }
      await this.database.completeOutbound(requestId, messageId);
      return messageId;
    } catch (error) {
      const code = error instanceof MetaGraphError ? error.code || `meta_http_${error.status}` : error.message;
      await this.database.failOutbound(requestId, code).catch(() => null);
      throw error;
    }
  }
}

function createServer(config = loadConfig(), dependencies = {}) {
  const gateway = dependencies.gateway || new Gateway(config, dependencies);
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);

    if (request.method === "GET" && url.pathname === "/health") {
      json(response, 200, { status: "healthy", service: "meta-wa-gateway" });
      return;
    }
    if (request.method === "GET" && url.pathname === "/ready") {
      const missing = missingConfig(config);
      try {
        if (!missing.length) await gateway.database.ready();
        json(response, missing.length ? 503 : 200, { ready: !missing.length, missing });
      } catch {
        json(response, 503, { ready: false, missing: ["APP_DATABASE_DSN"] });
      }
      return;
    }
    if (request.method === "GET" && url.pathname === "/webhooks/whatsapp") {
      const mode = url.searchParams.get("hub.mode");
      const token = url.searchParams.get("hub.verify_token");
      const challenge = url.searchParams.get("hub.challenge") || "";
      if (mode === "subscribe" && safeEqual(token, config.verifyToken)) {
        response.writeHead(200, { "content-type": "text/plain" });
        response.end(challenge);
      } else {
        response.writeHead(403).end();
      }
      return;
    }
    if (request.method === "POST" && url.pathname === "/webhooks/whatsapp") {
      let raw;
      try {
        raw = await readBody(request, MAX_WEBHOOK_BYTES);
      } catch {
        json(response, 413, { error: "body_too_large" });
        return;
      }
      if (!validSignature(raw, request.headers["x-hub-signature-256"], config.appSecret)) {
        json(response, 401, { error: "invalid_signature" });
        return;
      }
      let payload;
      try {
        payload = JSON.parse(raw.toString("utf8"));
      } catch {
        json(response, 400, { error: "invalid_json" });
        return;
      }
      try {
        await gateway.acceptWebhook(payload);
      } catch (error) {
        gateway.logger?.error?.("Meta webhook persistence failed:", error);
        json(response, 503, { error: "persistence_unavailable" });
        return;
      }
      json(response, 200, { accepted: true });
      gateway.scheduleWebhook(payload);
      return;
    }
    if (request.method === "GET" && url.pathname === "/internal/v1/status") {
      if (!safeEqual(request.headers["x-bridge-token"], config.bridgeToken)) {
        json(response, 403, { status: "forbidden" });
        return;
      }
      json(response, 200, {
        connection: missingConfig(config).length ? "not_configured" : "connected",
        me: config.businessPhone || config.phoneNumberId,
        provider: "meta_cloud_api",
      });
      return;
    }
    if (request.method === "POST" && url.pathname === "/internal/v1/messages") {
      if (!safeEqual(request.headers["x-bridge-token"], config.bridgeToken)) {
        json(response, 403, { status: "forbidden" });
        return;
      }
      try {
        const raw = await readBody(request, MAX_INTERNAL_BYTES);
        const payload = JSON.parse(raw.toString("utf8"));
        const providerMessageId = await gateway.sendOutbound(payload);
        json(response, 200, { status: "sent", provider_message_id: providerMessageId });
      } catch (error) {
        const status = Number(error.status || (error instanceof MetaGraphError ? 502 : 400));
        json(response, status, {
          status: "failed",
          error: String(error.message || error),
          error_code: error instanceof MetaGraphError ? error.code : null,
        });
      }
      return;
    }

    response.writeHead(404, { "content-type": "text/plain" });
    response.end("not found");
  });
  return { server, gateway };
}

if (require.main === module) {
  const config = loadConfig();
  const { server, gateway } = createServer(config);
  gateway.startRecovery();
  server.listen(config.port, config.host, () => {
    console.log(`${new Date().toISOString()} Meta WA gateway listening on http://${config.host}:${config.port}`);
  });
  const shutdown = () => {
    server.close(() => {
      gateway.close().then(() => process.exit(0), (error) => {
        console.error("Meta WA gateway shutdown failed:", error);
        process.exit(1);
      });
    });
  };
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
}

module.exports = {
  Gateway,
  createServer,
  safeEqual,
  validSignature,
  readBody,
};
