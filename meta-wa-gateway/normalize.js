"use strict";

const path = require("node:path");

function digits(value) {
  return String(value || "").replace(/\D/g, "");
}

function waIdToJid(waId) {
  const phone = digits(waId);
  return phone ? `${phone}@s.whatsapp.net` : "";
}

function jidToWaId(jid) {
  const value = String(jid || "").trim();
  if (value.includes("@") && !value.endsWith("@s.whatsapp.net")) return "";
  return digits(value.split("@")[0].split(":")[0]);
}

function inboundMessage(message) {
  if (!message || typeof message !== "object") return null;
  const id = String(message.id || "").trim();
  const waId = digits(message.from);
  if (!id || !waId) return null;
  if (message.type === "text" && typeof message.text?.body === "string") {
    return { id, waId, kind: "text", text: message.text.body };
  }
  if (message.type === "interactive") {
    const selected = message.interactive?.button_reply || message.interactive?.list_reply;
    if (selected?.id) return { id, waId, kind: "text", text: String(selected.id) };
  }
  if (message.type === "button" && message.button?.payload) {
    return { id, waId, kind: "text", text: String(message.button.payload) };
  }
  if (["image", "document"].includes(message.type)) {
    const media = message[message.type];
    if (media?.id) {
      return {
        id,
        waId,
        kind: "evidence",
        mediaId: String(media.id),
        mediaType: message.type,
        mimeType: String(media.mime_type || "application/octet-stream"),
        filename: path.basename(String(media.filename || "evidence")),
        caption: String(media.caption || ""),
      };
    }
  }
  return { id, waId, kind: "unsupported", messageType: String(message.type || "unknown") };
}

function webhookEvents(payload) {
  const messages = [];
  const statuses = [];
  for (const entry of payload?.entry || []) {
    for (const change of entry?.changes || []) {
      if (change?.field !== "messages") continue;
      for (const message of change.value?.messages || []) {
        const normalized = inboundMessage(message);
        if (normalized) messages.push(normalized);
      }
      for (const status of change.value?.statuses || []) {
        if (!status?.id || !status?.status) continue;
        statuses.push({
          messageId: String(status.id),
          status: String(status.status),
          timestamp: String(status.timestamp || ""),
          recipientWaId: digits(status.recipient_id),
          errorCode: status.errors?.[0]?.code ? String(status.errors[0].code) : null,
          errorTitle: status.errors?.[0]?.title ? String(status.errors[0].title) : null,
        });
      }
    }
  }
  return { messages, statuses };
}

module.exports = { digits, waIdToJid, jidToWaId, inboundMessage, webhookEvents };
