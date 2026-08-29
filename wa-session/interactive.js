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

async function sendInteractiveReply(sock, jid, message, payload, log = () => {}) {
  // Baileys 6 still accepts the classic button envelope on many linked-device
  // sessions. Keep it transport-only and opportunistic: if WhatsApp rejects it
  // or the response needs more than three actions, send a lossless text fallback.
  if (payload.actions.length > 0 && payload.actions.length <= 3) {
    const buttons = payload.actions.map((action) => ({
      buttonId: action.id,
      buttonText: { displayText: action.label },
      type: 1,
    }));
    try {
      await sock.sendMessage(
        jid,
        {
          text: payload.text,
          footer: payload.footer,
          buttons,
          headerType: 1,
        },
        { quoted: message },
      );
      return;
    } catch (error) {
      log(`native interactive reply failed; using text fallback: ${error}`);
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
