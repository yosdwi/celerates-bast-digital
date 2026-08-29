"use strict";

function nativeFlowSelection(content) {
  const params = content.interactiveResponseMessage?.nativeFlowResponseMessage?.paramsJson;
  if (!params) return "";
  try {
    const parsed = JSON.parse(params);
    return String(
      parsed.id ||
        parsed.selectedId ||
        parsed.selected_id ||
        parsed.buttonId ||
        parsed.button_id ||
        parsed.rowId ||
        parsed.row_id ||
        "",
    );
  } catch {
    return "";
  }
}

function messageText(message) {
  const content = message.message || {};
  return (
    content.buttonsResponseMessage?.selectedButtonId ||
    content.templateButtonReplyMessage?.selectedId ||
    content.listResponseMessage?.singleSelectReply?.selectedRowId ||
    nativeFlowSelection(content) ||
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    content.documentMessage?.caption ||
    ""
  );
}

function parseInteractiveReply(text) {
  try {
    const parsed = JSON.parse(text);
    if (!parsed || parsed.kind !== "interactive" || typeof parsed.text !== "string") return null;
    if (!Array.isArray(parsed.actions)) return null;
    const actions = parsed.actions
      .filter(
        (action) =>
          action &&
          typeof action.id === "string" &&
          action.id &&
          typeof action.label === "string" &&
          action.label,
      )
      .map((action) => ({ id: action.id, label: action.label }));
    return {
      text: parsed.text,
      footer: typeof parsed.footer === "string" ? parsed.footer : "Digital BAST",
      actions,
    };
  } catch {
    return null;
  }
}

function typedOptionsHint(payload) {
  if (!payload.actions.length) return "";
  return `Atau ketik: ${payload.actions.map((action) => action.label).join(", ")}`;
}

function fallbackText(payload) {
  const lines = [payload.text];
  if (payload.actions.length) {
    lines.push("", "Pilihan:");
    for (const action of payload.actions) {
      lines.push(`• ${action.label}: ${action.id}`);
    }
  }
  if (payload.footer) lines.push("", `_${payload.footer}_`);
  return lines.join("\n");
}

// WhatsApp's classic `buttonsMessage` envelope (buttonId/buttonText/type: 1)
// is now silently dropped by WhatsApp's own servers for most linked-device
// (non-Business-API) sessions -- Baileys' sendMessage call succeeds, nothing
// throws, the recipient just never sees the buttons. The nativeFlowMessage
// shape below is what WhatsApp's own current apps actually send, and is the
// same shape `messageText()` above already knows how to parse when a reply
// comes back -- this was previously never used on the sending side. Still
// not guaranteed (unofficial client), so `body.text` always embeds the
// typed-option hint too, in case it renders as plain text instead of chips.
//
// `messageVersion` is optional in the protobuf schema (WAProto
// Message.InteractiveMessage.NativeFlowMessage) so omitting it encodes fine
// locally and relayMessage() resolves without error -- but a live test
// against a real number showed the message never arrives at all (not even
// as a decrypt failure), which points at WhatsApp's server silently
// rejecting an unversioned native-flow payload during delivery routing.
// Real WhatsApp clients always send messageVersion: 1 for quick_reply
// buttons, so we do too.
function nativeFlowContent(payload) {
  const bodyText = [payload.text, "", typedOptionsHint(payload)].filter(Boolean).join("\n");
  return {
    interactiveMessage: {
      body: { text: bodyText },
      footer: { text: payload.footer },
      nativeFlowMessage: {
        buttons: payload.actions.map((action) => ({
          name: "quick_reply",
          buttonParamsJson: JSON.stringify({ display_text: action.label, id: action.id }),
        })),
        messageParamsJson: "",
        messageVersion: 1,
      },
    },
  };
}

async function sendInteractiveReply(sock, jid, message, payload, log = () => {}) {
  if (payload.actions.length > 0) {
    try {
      const { generateWAMessageFromContent } = require("@whiskeysockets/baileys");
      const full = generateWAMessageFromContent(jid, nativeFlowContent(payload), {
        userJid: sock.user?.id,
        quoted: message,
      });
      await sock.relayMessage(jid, full.message, { messageId: full.key.id });
      return;
    } catch (error) {
      log(`native-flow interactive reply failed; using text fallback: ${error}`);
    }
  }
  await sock.sendMessage(jid, { text: fallbackText(payload) }, { quoted: message });
}

module.exports = {
  fallbackText,
  messageText,
  parseInteractiveReply,
  sendInteractiveReply,
};
