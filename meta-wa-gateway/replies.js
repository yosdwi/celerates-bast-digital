"use strict";

const fs = require("node:fs");
const path = require("node:path");

function parsedEnvelope(text) {
  try {
    const parsed = JSON.parse(String(text || ""));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function interactivePayload(envelope) {
  const actions = Array.isArray(envelope?.actions)
    ? envelope.actions
        .filter((item) => item?.id && item?.label)
        .slice(0, 10)
        .map((item) => ({ id: String(item.id).slice(0, 256), label: String(item.label) }))
    : [];
  if (!actions.length) return null;
  const body = String(envelope.text || "Pilih salah satu opsi.").slice(0, 1024);
  const footer = String(envelope.footer || "Digital BAST").slice(0, 60);
  if (actions.length <= 3 && actions.every((item) => item.label.length <= 20)) {
    return {
      type: "button",
      body: { text: body },
      footer: { text: footer },
      action: {
        buttons: actions.map((item) => ({
          type: "reply",
          reply: { id: item.id, title: item.label.slice(0, 20) },
        })),
      },
    };
  }
  return {
    type: "list",
    body: { text: body },
    footer: { text: footer },
    action: {
      button: "Pilih menu",
      sections: [
        {
          title: "Digital BAST",
          rows: actions.map((item) => ({ id: item.id, title: item.label.slice(0, 24) })),
        },
      ],
    },
  };
}

function extractUrl(text) {
  const match = String(text || "").match(/https?:\/\/[^\s<>]+/u);
  if (!match) return null;
  const url = match[0].replace(/[),.;]+$/u, "");
  return { url, text: String(text).replace(match[0], "").trim() };
}

function fileEnvelope(envelope) {
  if (envelope?.kind !== "file" || !envelope.path) return null;
  const filePath = path.resolve(String(envelope.path));
  if (!fs.existsSync(filePath)) return null;
  return {
    path: filePath,
    filename: path.basename(String(envelope.filename || filePath)),
    caption: String(envelope.caption || ""),
  };
}

module.exports = { parsedEnvelope, interactivePayload, extractUrl, fileEnvelope };
