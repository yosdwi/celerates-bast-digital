"use strict";

// Build-time patch, applied to node_modules/whatsapp-web.js after install
// (see patch-stream-mode-enum.js for the same pattern and rationale).
//
// Root cause: window.WWebJS.sendMessage() builds the outgoing message
// object by spreading several option bags -- including `mediaOptions`,
// MediaData's own model -- on top of `id: newMsgKey`. MediaData carries a
// private `__x_id` field that ends up on the spread result too, colliding
// with Msg's internal `id` during Msg initialization: every media send
// (image, video, document) then fails inside getValidatedSender() with
// "Data passed to getter must include an id property (it's how we
// memoize) but got undefined". Text-only sends are unaffected (no
// mediaOptions spread). Confirmed against this exact error in production
// logs, 2026-09-21, for group document sends. Matches
// https://github.com/wwebjs/whatsapp-web.js/issues/201921,
// https://github.com/wwebjs/whatsapp-web.js/issues/201922, fixed upstream
// by https://github.com/wwebjs/whatsapp-web.js/pull/201923 (unreleased as
// of this session) -- same fix applied here as a build-time patch.

const fs = require("node:fs");
const path = require("node:path");

const target = path.join(
    __dirname,
    "node_modules",
    "whatsapp-web.js",
    "src",
    "util",
    "Injected",
    "Utils.js",
);

const before = `            ...extraOptions,
        };

        // Bot's won't reply if canonicalUrl is set (linking)`;

const after = `            ...extraOptions,
        };

        // digital-bast patch (2026-09-21): MediaData's private __x_id field
        // collides with Msg's internal id field when mediaOptions is spread
        // above, breaking getValidatedSender() during Msg initialization --
        // see patch-media-id-collision.js for the full diagnosis.
        delete message.__x_id;

        // Bot's won't reply if canonicalUrl is set (linking)`;

const source = fs.readFileSync(target, "utf8");
if (!source.includes(before)) {
    if (source.includes(after)) {
        console.log("patch-media-id-collision: already applied, skipping");
        process.exit(0);
    }
    console.error("patch-media-id-collision: expected source block not found -- whatsapp-web.js changed, review this patch");
    process.exit(1);
}
fs.writeFileSync(target, source.replace(before, after));
console.log("patch-media-id-collision: applied");
