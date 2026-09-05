# whatsapp-web-session (prototype)

Candidate replacement for `wa-session` (currently whatsmeow/Go), built on
[whatsapp-web.js](https://wwebjs.dev/) instead. **Prototype status: not
wired into production, not validated against real WhatsApp traffic yet.**
See `docs/wa-session-whatsapp-web-js-migration-plan.md` at the repo root for
the full rationale and rollout plan; this directory is step 1-2 of that
plan ("prototype in isolation" / "implement the 3-endpoint contract").

## Why this exists

`wa-session`'s WhatsApp connection got logged out 2026-09-02 (disk-full
during a whatsmeow SQLite upgrade, not a library bug -- see the migration
doc). The team wants to evaluate whatsapp-web.js as a replacement, based on
a colleague's experience running it stably. This directory is that
evaluation, kept completely separate from the real `wa-session` /
`bot-worker` containers so nothing here can affect production WhatsApp
traffic, redeploy the live session, or touch real data.

## What's implemented

The HTTP contract is a byte-for-byte match with the real bridge
(`whatsmeow-session/main.go`), so this is a genuine drop-in test, not a
simplified stand-in:

- `GET /internal/v1/status`, `POST /internal/v1/messages` -- same request/
  response shapes, same `x-bridge-token` auth, same outbound
  idempotency-by-`request_id` behavior.
- `GET /health`, `GET /ready` -- same shape.
- Calls `bot-worker`'s `POST /internal/v1/reply` the same way, with the same
  payload shapes (`kind: "text"|"evidence"`, `channel: "dm"` for DMs).

Behavior ported from `whatsmeow-session/bridge.go` and `helpers.go` (not
just the doc's "3 endpoints" summary -- these turned out to be load-bearing
when reading the real source):

- Group trigger matching (`@conform`, `!bast`, "bast bot", or an actual
  WhatsApp @-mention of the bot) and the evidence-in-group redirect.
- DM handling, including the digit-shortcut menu store
  (`helpers.js:MenuStore`) and the `interactive`/`file` JSON-envelope reply
  formats bot-worker can return.
- The "please wait" notice sent if bot-worker takes longer than
  `BOT_WAIT_NOTICE_DELAY_MS` (default 2500ms) for a non-fast-path message.
- Quoting the triggering message on every reply (`msg.reply()`).
- Export-file cleanup only after a confirmed send (kept on failure for
  retry/diagnosis); evidence temp files always cleaned up after the worker
  call completes.
- The "operator action required" latch: on a real logout, this does **not**
  auto re-pair. A marker file (`operator-action-required.json` next to the
  session store) survives a restart; clearing it requires hitting `/pair`
  explicitly. This is the guard against WhatsApp's anti-abuse system
  penalizing rapid reconnect loops -- don't remove it to "simplify".

## Known issue: pinned to an unreleased commit, not an npm version

`package.json` currently pins `whatsapp-web.js` to GitHub commit
`942d236a11ad68807308b058303ba5256915979c` on `main`, not an npm release. Found
during real pairing (2026-09-03): npm's latest, `1.34.7`, gets stuck --
`authenticated` fires, `loading_screen` reaches 100%, `ready` never fires --
or throws `Execution context was destroyed, most likely because of a
navigation` from inside `Client.inject()`. Root-caused against the library's
own issue tracker, not guessed:

- `wwebjs/whatsapp-web.js#127084` -- "Ready event never fires after
  authentication (v1.34.6, WhatsApp Web 2.3000.x)", closed, same symptom.
- `wwebjs/whatsapp-web.js#127082`/`#127083` -- "`inject()` fails after sleep/
  resume due to execution context destruction during page navigation" /
  the fix PR, merged 2026-03-12. **`1.34.7` (published 2026-04-24, after
  that merge) still ships the old, unfixed polling loop** -- confirmed by
  reading the installed `node_modules/whatsapp-web.js/src/Client.js`
  directly, the fix was not actually in that release despite the date
  making it look like it should be.

Also switched from Debian's `chromium` apt package to Puppeteer's own
bundled Chrome download (see the Dockerfile's comment) -- system Chromium
reproduced the `loading_screen`-100%-forever symptom on its own, per
`danpasecinic`'s comment on #127084. Costs more disk (Puppeteer downloads
its own Chrome binary in addition to the apt package's now-unused-but-still-
installed runtime libraries) -- worth revisiting if disk headroom gets
tight again.

**Revisit this pin once whatsapp-web.js cuts a release that actually
includes the `inject()` fix** -- check `node_modules/whatsapp-web.js/src/
Client.js` for `page.waitForFunction` instead of a manual `while` +
`page.evaluate()` polling loop around `window.Debug?.VERSION` / `window.Store`
before trusting a future npm version bump alone.

**Update 2026-09-03, same session:** that commit still wasn't enough --
paired successfully (confirmed on the phone's Linked Devices screen) but hung
at `loading_screen 99%` indefinitely, memory flat (not a leak, a genuine
hang). This is a *different*, currently-open bug: `wwebjs/whatsapp-web.js`
PR **#201853** ("fix: drive connection lifecycle from WhatsApp's Stream
model", open, not yet merged into `wwebjs/whatsapp-web.js` itself) explicitly
lists our exact symptom among five other open issues it targets. Re-pinned to
that PR's branch on its author's fork:
`github:Adi1231234/whatsapp-web.js#85443fa4c8f86111457590dd06564c3efe0f6d1d`.

This is now three unreleased fixes deep (two from upstream `main`, one from a
contributor's fork PR) just to get past initial connect. Read as a strong,
concrete signal for the whatsmeow-vs-whatsapp-web.js decision, not just a
prototype hiccup: whatsapp-web.js's reliance on WhatsApp Web's internal JS
`Store`/`Stream` objects makes it structurally fragile to WhatsApp's own
frontend changes, and it is *currently* in an active period of breakage --
multiple distinct "authenticated but never ready" reports from January 2026
through this PR's last update (2026-08-27). whatsmeow doesn't have this
category of risk at all (it never depends on WhatsApp Web's JS internals).
Worth weighing explicitly before committing to this library long-term, not
just patching through it.

**Update, same session, root cause found:** connected live to the actually-
running (stuck) Chrome via CDP (`puppeteer.connect({browserURL: ...})`
against the `DevToolsActivePort` file in the auth volume) instead of guessing
from more GitHub issues. Confirmed WhatsApp Web itself was fully loaded and
working (tab title `"(21) WhatsApp"`, real unread count) -- the hang is
entirely inside whatsapp-web.js. The PR #201853 fork's `resolveScreen()`
compares `Stream.mode`/`Stream.info` (real strings, confirmed live: `"MAIN"`/
`"NORMAL"`) against `StreamMode.MAIN`/`StreamInfo.NORMAL` pulled from
`window.require('WAWebStreamModel')` -- and on this WhatsApp Web build
(`2.3000.1046721733`), those enum export objects are **empty**, so
`M.MAIN`/`I.NORMAL` are `undefined`, no switch case ever matches, and it
falls through to `'ERROR'` forever. `patch-stream-mode-enum.js` (applied in
the Dockerfile, after `npm install`) patches `Client.js` to fall back to the
literal string values when the enum objects are empty. This is a from-
scratch fix, not sourced from an issue/PR -- not reported anywhere as of this
session. If a future whatsapp-web.js release fixes `WAWebStreamModel`'s
export or changes this code path, `patch-stream-mode-enum.js` fails loudly
(exits 1) rather than silently mismatching, so a future `npm install` breaking
on this is expected and means the patch should be removed, not debugged.

**Update, same session, the actual final blocker:** even with the enum patch
above, `ready` still never fired. Root-caused the same way (live CDP,
manually invoking `window.onAppStateHasSyncedEvent()` directly and reading
its rejection instead of guessing) to something unrelated to any of the
above: `Client.js`'s default `webVersionCache` is `LocalWebCache`, which
`fs.mkdirSync()`s a **relative** path (`./.wwebjs_cache/`) the first time a
version needs persisting. That write is incompatible with this container's
`read_only: true` rootfs -- and because it runs inside a fire-and-forget
browser-side call (`window.onAppStateHasSyncedEvent()`, never `await`ed on
the page side), the resulting rejection went nowhere: not a Node exception,
not a `client.on('error', ...)` emit (nothing was listening for one either,
now fixed), not a log line. It just silently stopped that async chain
partway through, before it ever reached the Stream-subscription code the
other two fixes were about. Fixed in `bridge.js` by passing
`webVersionCache: { type: 'none' }` to the `Client` constructor -- we always
want the live version anyway, so there's nothing to cache.

**Takeaway for next time**: when whatsapp-web.js hangs with zero further log
output and zero errors, don't trust "no errors" as "nothing failed" --
`page.evaluate()` callbacks that aren't awaited on the browser side swallow
their own rejections silently. Connect live via
`puppeteer.connect({browserURL: 'http://127.0.0.1:<port>'})` (port from
`<BOT_AUTH_DIR>/session/DevToolsActivePort`, second line) and manually
invoke the suspect `window.on*Event` function directly to see its real
rejection, rather than reading more GitHub issues.

**Update, same session: `ready` fixed, then `sendMessage()` broke.** Once
connected, `POST /internal/v1/messages` failed every time with `Cannot read
properties of undefined (reading 'id')`. Traced (again via live CDP, calling
`window.WWebJS.sendMessage()` and `window.WWebJS.getChat()` directly) to a
**different instance of the same `_serialized`-renamed-to-`$1` WhatsApp Web
change** discussed above -- this time in `Utils.js`'s `sendMessage()`, whose
last line looks up the just-sent message via
`Msg.get(newMsgKey._serialized)`. `wwebjs/whatsapp-web.js` has **six open,
unmerged community PRs** independently chasing pieces of this same rename
(#201848, #201850, #201852, #201862, #201869, plus the enum one already
covered) -- confirms the whole ecosystem is currently mid-breakage against a
very recent WhatsApp Web change, not just something specific to this setup.

Confirmed empirically before patching (important: don't assume "returns
undefined" means "the send failed") -- four test sends through the broken
code all showed up on the real WhatsApp account with `ack: 3` (delivered).
**The send itself worked every time; only the confirmation lookup failed.**
Patched in `patch-serialized-rename.js` (same build-time pattern as the enum
patch): `newMsgKey._serialized ?? newMsgKey.$1` in `sendMessage()`'s final
lookup, and the equivalent in `getMessageModel()`'s `msg.id.remote`
handling. Both fail loudly (exit 1) if whatsapp-web.js's source no longer
matches, same as the enum patch.

**Update, same session: inbound messages hit the same rename, in
`getChatModel()`.** A real inbound DM from a second real number, on this
prototype's own `_handleMessage` -> `msg.getChat()` -> `Client.getChatById()`
path, failed with the same opaque minified `r: r` DataError -- matches
`wwebjs/whatsapp-web.js` issues **#201845** ("`Client.getState()` and
`Client.getChats()` throws `r: r` despite client being CONNECTED") and
**#201869** ("guard undefined `lastReceivedKey._serialized` in
`getChatModel`"), both open/unmerged. Same root cause, different call sites:
`getChatModel()`'s group-chat `chat.id._serialized` and its
`chat.lastReceivedKey._serialized` lastMessage lookup. Patched the same way,
now also in `patch-serialized-rename.js` -- and the lastMessage lookup is
now guarded so an unresolvable key returns nothing instead of reaching
IndexedDB with `undefined` and throwing.

**Deliberately NOT patched**: three more `_serialized` sites exist in
`Utils.js` (`editMessage()`'s final lookup, `rejectCall()`, group-membership-
request approval) -- none are on any path this prototype actually exercises
(we don't edit messages, reject calls, or approve group join requests), so
patching them now would be untested speculation. If a future feature needs
one of those, check for `_serialized` there first rather than assuming it's
fine.

**Separately, still open**: inbound *media* (`message.downloadMedia()`)
fails with the same `r: r` pattern -- matches `wwebjs/whatsapp-web.js`
**#201830**/**#201833** (message key `_serialized` renamed to `$1` breaks
`downloadMedia()` for all incoming media on WA Web 2.3000.1043159177+), also
open/unmerged. Not yet patched here -- next thing to fix if evidence-upload
(the DM `kind:"evidence"` path) needs to work before this goes further.

**Update, same session: full text send/receive round trip confirmed working
end-to-end against the real account** (three separate real inbound DMs from
a second real number, each correctly received, routed to `stub-worker`, and
replied to -- verified by reading the actual chat's message list live via
CDP, not just trusting a 200 response). One scare along the way turned out
to be a **false alarm caused by this prototype's own missing logging**, not
a bug: `_reply()` never logged anything on success, only on failure, so a
message that round-tripped correctly looked indistinguishable from a hang in
the logs. Fixed by adding a `reply sent in=<id>` log line on success (and a
`msgId()` helper applying the `_serialized`/`$1` fallback consistently to
every trace-id log line, replacing several `in=undefined` lines). No code
in the actual send/receive path needed to change for this -- it was already
correct.

**Lesson for next time (this cost real debugging time)**: before concluding
something is stuck because logs go quiet, check whether the code path in
question logs anything on its *success* branch at all -- a silent success
and a silent hang look identical in a log stream. Confirm end state (here:
read the actual WhatsApp chat via CDP) before restarting containers or
writing new patches to "fix" a problem that may not exist.

**Update, same session: fixed the media-download rename bug, and found it's
much bigger than one method.** `Message.js`'s `downloadMedia()` passes
`this.id._serialized` to `resolveMediaBlob()` -- undefined for the same
reason as everywhere else in this doc. But grepping `Message.js` turned up
**20+ other call sites** reading `this.id._serialized` directly (`reply()`,
`react()`, `forward()`, `edit()`, `delete()`, `getQuotedMessage()`,
`getMentions()`, `downloadMedia()`, ...) -- essentially every non-trivial
method on a received message. Patching each individually would be a lot of
surface to get right and keep in sync. Instead, patched **once**, in
`Message.js`'s `_patch()` where `this.id = data.id` is first assigned:
normalize `_serialized` from `$1` right there, so every method downstream
reads a correctly-populated `this.id` without needing its own fix. Added to
`patch-serialized-rename.js` (now patches both `Utils.js` and `Message.js`).

Worth naming plainly: this means the reply messages sent during the earlier
"false alarm" round-trip test likely went out **without a working quote/
reply-context** (`quotedMessageId: this.id._serialized` was undefined at the
time), even though the text itself delivered correctly -- the message
content was never in doubt, only the visual "replying to X" quote marker.
Not re-verified after this patch; worth confirming quoting actually renders
correctly next time a real inbound test happens.

## Staying off WhatsApp's anti-abuse radar

Both whatsmeow and whatsapp-web.js are unofficial clients; WhatsApp can rate-limit or
ban an account regardless of library choice. What actually matters is usage pattern and
deploy discipline (see the migration doc's "Why" section). Concretely, in this
implementation:

- **Exactly one companion client per account, always.** Pairing this prototype and the
  real wa-session to the same number at the same time means WhatsApp mirrors every
  message to both, and both independently reply -- duplicate, visibly broken behavior
  in real chats, not just a ban risk. Before any real pairing (test or production
  number), confirm the other bridge is not also mid-pairing or connected (`GET
  /internal/v1/status` on the other one).
- **No auto-retry pairing loop after a real logout.** This is what `state.js`'s
  `operator-action-required.json` marker exists for -- ported deliberately from
  `whatsmeow-session/state_guard.go`. WhatsApp penalizes rapid reconnect churn; a
  crash-looping container that keeps re-requesting a QR is exactly that pattern. Don't
  remove this latch to "simplify" a restart flow.
- **Deploy discipline**: this image is built from its own Dockerfile (not FROM the app
  image) and is deliberately excluded from any automated blue/green flow, mirroring
  `whatsmeow-session`'s separation -- recreating the container that holds the live
  session forces a reconnect. When this moves past prototype, it needs the same
  `scripts/deploy-wa-session.sh`-style manual, rarely-run deploy path, not the app's
  normal redeploy-on-every-push flow.
- **No unsolicited/bulk sending.** Everything here is reactive (replies to an inbound
  trigger) or a single explicit `/internal/v1/messages` call from the app -- there is no
  broadcast/blast path in this codebase, and none should be added without separately
  re-litigating the ban-risk tradeoff.
- **Session persistence across restarts.** `LocalAuth`'s profile directory
  (`BOT_AUTH_DIR`, volume-backed) is the actual login state; losing it forces a brand
  new pairing, which is the disruptive event to avoid, not routine restarts.
- **Version drift risk (stability, not directly ban-risk)**: whatsapp-web.js works by
  driving the real WhatsApp Web client, so a WhatsApp-side web client change can break
  it until the library catches up -- pinned here at `1.26.0`. This is a real operational
  cost whatsmeow doesn't have (whatsmeow reimplements the wire protocol directly); watch
  upstream releases once this is more than a prototype.

## What's deliberately NOT done here

- No group allowlist enforcement. Reading the real Go source: `isAllowedGroup`
  is defined but **never called** from the message path -- only used to
  render checkboxes on the setup page. `wa-session/README.md` confirms this
  in writing: "`BOT_ALLOWED_GROUPS` and the old `/allow` setup action are no
  longer used. The policy is intentionally all joined groups + explicit
  mention/trigger." So this prototype doesn't implement an allowlist either
  -- that would be adding scope the real system doesn't have, not parity.
- No phone-number pairing code (only QR). whatsapp-web.js's pairing-code API
  has moved across versions; needs to be checked against whatever version
  ends up pinned before it's worth implementing.
- No systemd/manual-deploy story yet (mirrors `scripts/deploy-wa-session.sh`)
  -- out of scope until the prototype is actually validated.

## Open risk to validate empirically (can't be resolved by reading code)

`whatsmeow-session/identity.go` exists because whatsmeow's multi-device
protocol can address a DM sender by a "LID" (linked ID) instead of their
phone-number JID, and the bridge has to resolve one to the other to keep a
stable identity for menu state and the `jid` field sent to bot-worker. It is
not yet confirmed whether whatsapp-web.js (which drives the real
web.whatsapp.com client) ever surfaces that same LID/phone-number split for
a 1:1 chat, since this is a WhatsApp-side identity change, not a whatsmeow-
specific one. `bridge.js` currently uses `message.author || message.from` as
a best-effort stand-in (see the comment at the top of that file) --
**confirm this against a real paired account before trusting it**,
especially for any contact using WhatsApp's "privacy" LID mode.

## Isolation

`compose.prototype.yaml` is a **separate compose project** (own directory,
own docker network, own volume, own secret) -- not merged into the root
`compose.yaml`, shares nothing with the real `wa-session`/`bot-worker`
containers or their data. `stub-worker.js` stands in for the real
`bot-worker` so a full send/receive round trip can be tested without
shelling out to the actual `digital-bast` CLI or touching production data.

```bash
cd whatsapp-web-session
mkdir -p dev-secrets && openssl rand -hex 32 > dev-secrets/bridge_token
docker compose -f compose.prototype.yaml up --build
```

Open <http://127.0.0.1:18090> (loopback only, distinct port from the real
wa-session's 8090 so both can run side by side). **Pair a test WhatsApp
number here, never the production one.** Send it a DM or `@conform`-mention
it in a group it has joined; `stub-worker.js` echoes back what it received
(and replies to literal `menu` with a canned interactive envelope, to
exercise the digit-shortcut path).

Resource limits (`compose.prototype.yaml`, currently 1 CPU / 1G) are a
starting guess, not a measured number -- whatsapp-web.js runs Chromium
24/7, unlike bast-renderer's per-request pattern. Watch actual steady-state
memory over a few days before reusing these limits anywhere real (see the
migration doc's "Resource footprint" section).

To tear down and reclaim disk:

```bash
docker compose -f compose.prototype.yaml down -v
docker image rm whatsapp-web-session-whatsapp-web-session whatsapp-web-session-stub-worker 2>/dev/null
```

## Next steps (not started)

1. Pair a test number, confirm QR flow, send, receive (text + evidence +
   group trigger) all work end-to-end against this stub setup.
2. Point `BOT_WORKER_BASE_URL` at a **local, non-production** `bot-worker`
   instance (own checkout, own `.env`, not the deployed container) to
   validate the full round trip through the real `digital-bast` CLI, still
   without touching production data.
3. Resolve the LID/identity question above against the real paired account.
4. Only after the above: plan the side-by-side/cutover steps from the
   migration doc's "Suggested rollout approach" -- this directory does not
   attempt that yet.
