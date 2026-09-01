"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { waIdToJid, jidToWaId, inboundMessage, webhookEvents } = require("./normalize");

test("Meta wa_id maps to the existing canonical phone JID", () => {
  assert.equal(waIdToJid("+62 812-3456"), "628123456@s.whatsapp.net");
  assert.equal(jidToWaId("628123456:7@s.whatsapp.net"), "628123456");
});

test("linked-device-only identifiers are never treated as Meta recipients", () => {
  assert.equal(jidToWaId("123456789@lid"), "");
  assert.equal(jidToWaId("628123456789@s.whatsapp.net"), "628123456789");
});

test("interactive button and list IDs become deterministic worker text", () => {
  assert.deepEqual(
    inboundMessage({
      id: "wamid.button",
      from: "6281",
      type: "interactive",
      interactive: { button_reply: { id: "attendance", title: "Attendance" } },
    }),
    { id: "wamid.button", waId: "6281", kind: "text", text: "attendance" },
  );
  assert.equal(
    inboundMessage({
      id: "wamid.list",
      from: "6281",
      type: "interactive",
      interactive: { list_reply: { id: "tasklist" } },
    }).text,
    "tasklist",
  );
});

test("webhook extraction returns inbound messages and delivery statuses", () => {
  const result = webhookEvents({
    entry: [
      {
        changes: [
          {
            field: "messages",
            value: {
              messages: [{ id: "wamid.in", from: "6281", type: "text", text: { body: "menu" } }],
              statuses: [
                {
                  id: "wamid.out",
                  status: "delivered",
                  timestamp: "1780000000",
                  recipient_id: "6281",
                },
              ],
            },
          },
        ],
      },
    ],
  });
  assert.equal(result.messages[0].text, "menu");
  assert.equal(result.statuses[0].status, "delivered");
});

test("image and document payloads normalize as evidence", () => {
  const image = inboundMessage({
    id: "wamid.image",
    from: "6281",
    type: "image",
    image: { id: "media-1", mime_type: "image/jpeg", caption: "task 1" },
  });
  assert.equal(image.kind, "evidence");
  assert.equal(image.mediaId, "media-1");
  assert.equal(image.caption, "task 1");
});
