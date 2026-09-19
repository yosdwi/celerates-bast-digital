"use strict";

// Build-time patch, applied to node_modules/whatsapp-web.js after install
// (see patch-stream-mode-enum.js for the same pattern and rationale).
//
// Root cause: WhatsApp Web renamed the `_serialized` property on WID/message-
// key objects to `$1` on recent builds -- a broad, codebase-wide rename, not
// specific to one object type (matches wwebjs/whatsapp-web.js issues #201848,
// #201850, #201862, #201869, all open/unmerged as of 2026-09-03; six
// different community PRs are independently chasing pieces of this same
// rename). `window.WWebJS.sendMessage()`'s final line looks the just-sent
// message back up via `Msg.get(newMsgKey._serialized)` -- with `_serialized`
// undefined, this returns nothing even though the send itself (awaited
// `addAndSendMsgToChat`) already succeeded. Confirmed live via CDP,
// 2026-09-03: four test messages sent through this exact path all showed
// `ack: 3` (delivered) on the actual WhatsApp account, while `sendMessage()`
// returned undefined every time because of this one lookup. See README.md.

const fs = require("node:fs");
const path = require("node:path");

const utilsTarget = path.join(
    __dirname,
    "node_modules",
    "whatsapp-web.js",
    "src",
    "util",
    "Injected",
    "Utils.js",
);

const messageTarget = path.join(
    __dirname,
    "node_modules",
    "whatsapp-web.js",
    "src",
    "structures",
    "Message.js",
);

// `this.id._serialized` is read directly in 20+ places across Message.js
// (reply, react, forward, downloadMedia, edit, getQuotedMessage, ...) --
// confirmed live (message.downloadMedia() failing, and this prototype's own
// `msgId()` helper needing a `?? msg.id.$1` fallback for every logged
// message id). Patching each call site individually would be a lot of
// surface to get right; normalizing once in the constructor, where `this.id`
// is first assigned from `data.id`, fixes every method that reads
// `this.id._serialized` without touching them.
const messageReplacements = [
    {
        name: "Message._patch() id normalization",
        before: `        /**
         * ID that represents the message
         * @type {object}
         */
        this.id = data.id;`,
        after: `        /**
         * ID that represents the message
         * @type {object}
         */
        this.id = data.id;
        // digital-bast patch (2026-09-03): _serialized -> $1 rename, applied
        // once here instead of at each of the 20+ call sites in this file
        // that read this.id._serialized. See patch-serialized-rename.js.
        if (this.id && this.id._serialized === undefined && this.id.$1 !== undefined) {
            this.id = { ...this.id, _serialized: this.id.$1 };
        }`,
    },
];

const replacements = [
    {
        name: "getChatModel() group chatWid",
        before: `        if (chat.groupMetadata) {
            model.isGroup = true;
            const chatWid = window
                .require('WAWebWidFactory')
                .createWid(chat.id._serialized);`,
        after: `        if (chat.groupMetadata) {
            model.isGroup = true;
            // digital-bast patch (2026-09-03): _serialized -> $1 rename.
            const chatWid = window
                .require('WAWebWidFactory')
                .createWid(chat.id._serialized ?? chat.id.$1);`,
    },
    {
        name: "getChatModel() lastMessage lookup",
        before: `        model.lastMessage = null;
        if (model.msgs && model.msgs.length) {
            const lastMessage = chat.lastReceivedKey
                ? window
                      .require('WAWebCollections')
                      .Msg.get(chat.lastReceivedKey._serialized) ||
                  (
                      await window
                          .require('WAWebCollections')
                          .Msg.getMessagesById([
                              chat.lastReceivedKey._serialized,
                          ])
                  )?.messages?.[0]
                : null;`,
        after: `        model.lastMessage = null;
        if (model.msgs && model.msgs.length) {
            // digital-bast patch (2026-09-03): _serialized -> $1 rename, plus
            // a guard so an unresolvable key doesn't reach IndexedDB with an
            // undefined key (that throws instead of just returning nothing).
            const lastReceivedKeyId = chat.lastReceivedKey
                ? (chat.lastReceivedKey._serialized ?? chat.lastReceivedKey.$1)
                : null;
            const lastMessage = lastReceivedKeyId
                ? window
                      .require('WAWebCollections')
                      .Msg.get(lastReceivedKeyId) ||
                  (
                      await window
                          .require('WAWebCollections')
                          .Msg.getMessagesById([lastReceivedKeyId])
                  )?.messages?.[0]
                : null;`,
    },
    {
        name: "sendMessage() final Msg.get lookup",
        before: `        return window
            .require('WAWebCollections')
            .Msg.get(newMsgKey._serialized);
    };`,
        after: `        // digital-bast patch (2026-09-03): _serialized -> $1 rename, see
        // patch-serialized-rename.js for the full diagnosis.
        return window
            .require('WAWebCollections')
            .Msg.get(newMsgKey._serialized ?? newMsgKey.$1);
    };`,
    },
    {
        name: "getMessageModel() msg.id.remote serialization",
        before: `        if (typeof msg.id.remote === 'object') {
            msg.id = Object.assign({}, msg.id, {
                remote: msg.id.remote._serialized,
            });
        }`,
        after: `        if (typeof msg.id.remote === 'object') {
            // digital-bast patch (2026-09-03): _serialized -> $1 rename.
            msg.id = Object.assign({}, msg.id, {
                remote: msg.id.remote._serialized ?? msg.id.remote.$1,
            });
        }`,
    },
];

function applyPatches(target, patches) {
    let source = fs.readFileSync(target, "utf8");
    let appliedCount = 0;
    let alreadyCount = 0;
    for (const { name, before, after } of patches) {
        if (source.includes(after)) {
            alreadyCount += 1;
            continue;
        }
        if (!source.includes(before)) {
            console.error(`patch-serialized-rename: expected block not found for "${name}" in ${target} -- whatsapp-web.js changed, review this patch`);
            process.exit(1);
        }
        source = source.replace(before, after);
        appliedCount += 1;
    }
    if (appliedCount > 0) fs.writeFileSync(target, source);
    return { appliedCount, alreadyCount };
}

const utilsResult = applyPatches(utilsTarget, replacements);
const messageResult = applyPatches(messageTarget, messageReplacements);
console.log(
    `patch-serialized-rename: Utils.js applied ${utilsResult.appliedCount}, already present ${utilsResult.alreadyCount}; ` +
    `Message.js applied ${messageResult.appliedCount}, already present ${messageResult.alreadyCount}`,
);
