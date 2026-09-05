"use strict";

// Build-time patch, applied to node_modules/whatsapp-web.js after install.
// Not upstreamable as-is (root cause is specific to a WhatsApp Web build
// this repo happened to hit); see README.md "Known issue" section for the
// full diagnosis via live CDP inspection, 2026-09-03.
//
// Root cause: whatsapp-web.js's Stream-model connection-lifecycle patch
// (github.com/wwebjs/whatsapp-web.js PR #201853, pulled in via the
// Adi1231234 fork pin in package.json) compares `Stream.mode`/`Stream.info`
// against `StreamMode.MAIN`/`StreamInfo.NORMAL` pulled from
// `window.require('WAWebStreamModel')`. On WhatsApp Web build
// 2.3000.1046721733 (confirmed live via Puppeteer CDP against the actual
// stuck page), that module's `StreamMode`/`StreamInfo` exports are empty
// objects -- `Stream.mode`/`Stream.info` themselves still return correct
// plain strings ("MAIN"/"NORMAL"), just not the enum object used to
// interpret them. `M.MAIN` is therefore `undefined`, the switch/ternary
// never matches, `resolveScreen()` falls through to 'ERROR' forever, and
// `ready` never fires -- authentication succeeds, WhatsApp Web is fully
// loaded and usable in the browser, but the library never notices.

const fs = require("node:fs");
const path = require("node:path");

const target = path.join(__dirname, "node_modules", "whatsapp-web.js", "src", "Client.js");

const before = `                            const {
                                Stream,
                                StreamMode: M,
                                StreamInfo: I,
                            } = window.require('WAWebStreamModel');
                            // WA >= 2.3000.1046055909 moved displayInfo out of
                            // the model into WAWebStreamGetters. Whichever a
                            // build has answers; deriving it does not work, no
                            // combination of the inputs is equivalent.
                            const displayInfo = () =>
                                window
                                    .require('WAWebStreamGetters')
                                    ?.getDisplayInfo?.(Stream) ??
                                Stream.displayInfo;
                            const resolveScreen = () => {
                                switch (Stream.mode) {
                                    case M.MAIN:
                                        return displayInfo() === I.NORMAL
                                            ? 'CONNECTED'
                                            : 'LOADING';
                                    case M.QR:
                                        return 'QR';
                                    case M.OFFLINE:
                                        return 'DISCONNECTED';
                                    case M.SYNCING:
                                        return 'LOADING';
                                    default:
                                        return 'ERROR';
                                }
                            };`;

const after = `                            const {
                                Stream,
                                StreamMode: M,
                                StreamInfo: I,
                            } = window.require('WAWebStreamModel');
                            // digital-bast patch (2026-09-03): this WA Web build ships
                            // empty StreamMode/StreamInfo enum objects -- Stream.mode/
                            // .info still return correct plain strings. Fall back to the
                            // literal values so this doesn't silently pin to 'ERROR'.
                            const M2 = M && M.MAIN ? M : { MAIN: 'MAIN', QR: 'QR', OFFLINE: 'OFFLINE', SYNCING: 'SYNCING' };
                            const I2 = I && I.NORMAL ? I : { NORMAL: 'NORMAL' };
                            // WA >= 2.3000.1046055909 moved displayInfo out of
                            // the model into WAWebStreamGetters. Whichever a
                            // build has answers; deriving it does not work, no
                            // combination of the inputs is equivalent.
                            const displayInfo = () =>
                                window
                                    .require('WAWebStreamGetters')
                                    ?.getDisplayInfo?.(Stream) ??
                                Stream.displayInfo;
                            const resolveScreen = () => {
                                switch (Stream.mode) {
                                    case M2.MAIN:
                                        return displayInfo() === I2.NORMAL
                                            ? 'CONNECTED'
                                            : 'LOADING';
                                    case M2.QR:
                                        return 'QR';
                                    case M2.OFFLINE:
                                        return 'DISCONNECTED';
                                    case M2.SYNCING:
                                        return 'LOADING';
                                    default:
                                        return 'ERROR';
                                }
                            };`;

const source = fs.readFileSync(target, "utf8");
if (!source.includes(before)) {
    if (source.includes(after)) {
        console.log("patch-stream-mode-enum: already applied, skipping");
        process.exit(0);
    }
    console.error("patch-stream-mode-enum: expected source block not found -- whatsapp-web.js changed, review this patch");
    process.exit(1);
}
fs.writeFileSync(target, source.replace(before, after));
console.log("patch-stream-mode-enum: applied");
