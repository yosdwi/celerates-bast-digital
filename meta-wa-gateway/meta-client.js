"use strict";

const fs = require("node:fs");

class MetaGraphError extends Error {
  constructor(message, status, code = null, details = null) {
    super(message);
    this.name = "MetaGraphError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function mimeFor(file) {
  const name = file.toLowerCase();
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
  if (name.endsWith(".webp")) return "image/webp";
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".csv")) return "text/csv";
  return "application/octet-stream";
}

class MetaClient {
  constructor(config, fetchImpl = fetch) {
    this.config = config;
    this.fetch = fetchImpl;
    this.base = `${config.graphBaseUrl}/${config.graphVersion}`;
  }

  async request(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.config.requestTimeoutMs);
    let response;
    try {
      response = await this.fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${this.config.accessToken}`,
          ...(options.headers || {}),
        },
      });
    } catch (error) {
      throw new MetaGraphError(String(error.message || error), 503);
    } finally {
      clearTimeout(timer);
    }
    const raw = await response.text();
    let parsed = {};
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch {
      parsed = { raw };
    }
    if (!response.ok) {
      const graph = parsed.error || {};
      throw new MetaGraphError(
        String(graph.message || `Meta Graph HTTP ${response.status}`),
        response.status,
        graph.code == null ? null : String(graph.code),
        parsed,
      );
    }
    return parsed;
  }

  async send(payload) {
    const result = await this.request(`${this.base}/${this.config.phoneNumberId}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messaging_product: "whatsapp", ...payload }),
    });
    return String(result.messages?.[0]?.id || "") || null;
  }

  sendText(to, text, contextMessageId = null) {
    return this.send({
      to,
      type: "text",
      text: { preview_url: true, body: String(text).slice(0, 4096) },
      ...(contextMessageId ? { context: { message_id: contextMessageId } } : {}),
    });
  }

  sendInteractive(to, interactive, contextMessageId = null) {
    return this.send({
      to,
      type: "interactive",
      interactive,
      ...(contextMessageId ? { context: { message_id: contextMessageId } } : {}),
    });
  }

  sendCtaUrl(to, text, url, contextMessageId = null) {
    return this.sendInteractive(
      to,
      {
        type: "cta_url",
        body: { text: String(text || "Buka Digital BAST").slice(0, 1024) },
        action: {
          name: "cta_url",
          parameters: { display_text: "Buka Talent Mobile", url },
        },
      },
      contextMessageId,
    );
  }

  sendTemplate(to, name, language, parameters = []) {
    const components = parameters.length
      ? [{ type: "body", parameters: parameters.map((text) => ({ type: "text", text: String(text) })) }]
      : [];
    return this.send({
      to,
      type: "template",
      template: { name, language: { code: language }, components },
    });
  }

  async markRead(messageId) {
    return this.send({ status: "read", message_id: messageId });
  }

  async mediaInfo(mediaId) {
    return this.request(`${this.base}/${mediaId}`);
  }

  async downloadMedia(mediaId) {
    const info = await this.mediaInfo(mediaId);
    if (!info.url) throw new MetaGraphError("Meta media URL missing", 502);
    const response = await this.fetch(info.url, {
      headers: { Authorization: `Bearer ${this.config.accessToken}` },
    });
    if (!response.ok) throw new MetaGraphError(`Meta media download HTTP ${response.status}`, response.status);
    return { buffer: Buffer.from(await response.arrayBuffer()), mimeType: String(info.mime_type || "") };
  }

  async uploadMedia(filePath, mimeType = null) {
    const form = new FormData();
    form.append("messaging_product", "whatsapp");
    form.append("type", mimeType || mimeFor(filePath));
    form.append("file", new Blob([fs.readFileSync(filePath)], { type: mimeType || mimeFor(filePath) }), filePath.split("/").pop());
    const result = await this.request(`${this.base}/${this.config.phoneNumberId}/media`, {
      method: "POST",
      body: form,
    });
    if (!result.id) throw new MetaGraphError("Meta media upload ID missing", 502);
    return String(result.id);
  }

  async sendFile(to, file, contextMessageId = null) {
    const mime = mimeFor(file.path);
    const mediaId = await this.uploadMedia(file.path, mime);
    const isImage = mime.startsWith("image/");
    const type = isImage ? "image" : "document";
    return this.send({
      to,
      type,
      [type]: {
        id: mediaId,
        ...(isImage ? {} : { filename: file.filename }),
        ...(file.caption ? { caption: file.caption.slice(0, 1024) } : {}),
      },
      ...(contextMessageId ? { context: { message_id: contextMessageId } } : {}),
    });
  }
}

module.exports = { MetaClient, MetaGraphError, mimeFor };
