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
      // False only when `text` already asks for a bare-number reply for
      // something else (e.g. dm_workflow._attendance_status_reply's own
      // evidence-candidate list) -- see interactive.py on the Python side.
      digitShortcuts: parsed.digitShortcuts !== false,
    };
  } catch {
    return null;
  }
}

function fallbackText(payload) {
  const lines = [payload.text];
  if (payload.actions.length) {
    lines.push("");
    if (payload.digitShortcuts !== false) {
      payload.actions.forEach((action, index) => {
        lines.push(`${index + 1}. ${action.label}`);
      });
    } else {
      for (const action of payload.actions) {
        lines.push(`• ${action.label}: ${action.id}`);
      }
    }
  }
  if (payload.footer) lines.push("", `_${payload.footer}_`);
  return lines.join("\n");
}

// Tapping a button became typing its number instead (see sendInteractiveReply
// below -- native-flow buttons don't reliably deliver on this account, see
// the disabled code further down). rememberMenu records the exact options
// just shown to a JID so the next bare-digit reply can resolve back to the
// real action id -- this matters most for PMO's per-request approve/reject
// ids (e.g. "pmo:attendance:<uuid>:approve"), which nobody could reasonably
// type by hand otherwise. forgetMenu is called on every non-interactive
// reply so a stale menu never shadows the Python CLI's own, unrelated
// bare-number flow (picking an outstanding evidence/attendance item from a
// plain numbered list) -- only a digit typed immediately after an
// interactive menu was shown is treated as a menu selection.
const PENDING_MENU_TTL_MS = 15 * 60 * 1000;
const MAX_PENDING_MENUS = 512;
const pendingMenus = new Map();

function rememberMenu(jid, actions) {
  pendingMenus.set(jid, { actions, expiresAt: Date.now() + PENDING_MENU_TTL_MS });
  if (pendingMenus.size <= MAX_PENDING_MENUS) return;
  const oldest = pendingMenus.keys().next().value;
  if (oldest !== undefined) pendingMenus.delete(oldest);
}

function forgetMenu(jid) {
  pendingMenus.delete(jid);
}

function resolveDigitReply(jid, text) {
  const trimmed = text.trim();
  if (!/^[0-9]+$/.test(trimmed)) return text;
  const entry = pendingMenus.get(jid);
  if (!entry || Date.now() > entry.expiresAt) return text;
  const action = entry.actions[Number(trimmed) - 1];
  return action ? action.id : text;
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
  const hint = payload.actions.length
    ? `Atau ketik: ${payload.actions.map((action) => action.label).join(", ")}`
    : "";
  const bodyText = [payload.text, "", hint].filter(Boolean).join("\n");
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

// Disabled 2026-08-29: three live sends (two JIDs, with and without
// messageVersion set) all returned success from relayMessage() with zero
// exception and zero WhatsApp-side error/receipt, yet nothing ever reached
// the recipient -- not the buttons, not even plain text. Because relayMessage
// never throws in this failure mode, the try/catch fallback below never ran,
// so every real talent interaction that hit this path (any bot reply with
// buttons, e.g. the main menu) was silently dropped in production -- strictly
// worse than the original bug (legacy buttonsMessage silently stripped by
// WhatsApp but the surrounding text still delivered). Until there's a
// confirmed-working way to send native-flow interactive messages from this
// account, always use the text fallback; nativeFlowContent is kept for the
// next investigation rather than deleted.
async function sendInteractiveReply(sock, jid, message, payload, log = () => {}) {
  await sock.sendMessage(jid, { text: fallbackText(payload) }, { quoted: message });
}

module.exports = {
  fallbackText,
  forgetMenu,
  messageText,
  parseInteractiveReply,
  rememberMenu,
  resolveDigitReply,
  sendInteractiveReply,
};
