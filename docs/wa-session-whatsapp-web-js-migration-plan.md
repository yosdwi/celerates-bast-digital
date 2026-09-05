# wa-session Migration: whatsmeow (Go) → whatsapp-web.js (Node)

**Status: CUT OVER, 2026-09-04.** `wa-session` (whatsmeow) is stopped;
`whatsapp-web-session` (whatsapp-web.js) is the live production WhatsApp transport,
paired to the real bot number, serving real `bot-worker`/`digital-bast` CLI traffic.
`BOT_BRIDGE_BASE_URL` on every app-anchor container (`web-blue`, `web-green`, `worker`,
`runner`) points at it. Cutover was compressed into the same extended session that did
the validation work below, at the user's explicit direction, on the reasoning that
`wa-session` had no live session to lose (disconnected since the 2026-09-02 incident)
-- so redirecting to a proven-working transport was a net fix, not a new risk.

Deliberately skipped/shortened from the original staged plan below: the multi-day
Phase B observation window (memory trend, WhatsApp-side stability) never happened --
watch this in production instead of a controlled pre-cutover window. `whatsmeow-session/`
and `wa-session/` (the even-older Baileys code) are left in place, untouched, as
rollback data, matching the discipline of every prior transport migration here.
**Not yet pushed to GitHub** -- everything above (compose.yaml, scripts, the
whatsapp-web-session/ service itself) exists only on the production host's local
checkout; push and PR this before the host's disk/containers get rebuilt from the
real pipeline, or it's gone.

One operational mistake worth recording: the first `docker compose up --no-deps`
recreate of `web-green` used `SECRETS_GID=0` (a `check-ops.sh`-style CI placeholder,
correct only for static `compose config` validation) instead of the real value (`1000`,
the `debian` group that owns `secrets/`) -- this caused a real ~4 minute outage
(`/run/secrets/*` permission denied, container crash-looping, public health 502) before
being caught and fixed. Never reuse `check-ops.sh`'s placeholder env block for an
actual container recreate.

---

**Original status (superseded above):** Design only — not implemented. Written
2026-09-03 after investigating the current architecture directly on the running
production containers.

## Why

The current `wa-session` service (Go, using the [whatsmeow](https://github.com/tulir/whatsmeow)
library) logged the linked WhatsApp device out on 2026-09-02, root-caused to the host
disk filling up (`disk I/O error: no space left on device` while whatsmeow tried to
upgrade its SQLite session store). Re-pairing requires an operator to scan a QR code or
enter a pairing code via `wa-session`'s `/setup/status` page (bound to `127.0.0.1:8090`
only, not internet-reachable — an operator with server shell access has to trigger it
and relay the QR/code to whoever holds the phone).

The user wants to replace whatsmeow with [whatsapp-web.js](https://wwebjs.dev/) instead,
based on a colleague's experience running it stably long-term. Important context to carry
into the actual migration decision: **the 2026-09-02 incident was a disk-space problem,
not a whatsmeow reliability problem** — switching libraries does not by itself prevent a
repeat of that specific failure. Both whatsmeow and whatsapp-web.js are unofficial
WhatsApp Web protocol implementations; neither is blessed by Meta, and either can get an
account rate-limited/banned if used for bulk/spammy sending. Long-term stability is
mostly about *usage pattern* (message volume/rate, avoiding mass unsolicited sends) and
*infrastructure hygiene* (disk space, not repeatedly re-pairing), not the library choice
per se. That said, whatsapp-web.js does have one real advantage worth naming: because it
drives an actual Chromium session against the real web.whatsapp.com client, its traffic
is byte-for-byte indistinguishable from a human using WhatsApp Web in a browser — there
is no separate protocol implementation for WhatsApp's anti-abuse systems to fingerprint
as non-standard, which is the concrete mechanism behind "feels safer" reports for
long-running bots. That's a real, if hard-to-quantify, edge; it comes at the cost of
running a full browser process continuously (see Resource footprint below) rather than
whatsmeow's lightweight native-protocol connection.

## Current architecture (verified against the running containers, 2026-09-03)

Three services, cleanly separated by a narrow HTTP contract:

```
WhatsApp  <──────────────────────────►  wa-session (Go / whatsmeow)
                                              │  ▲
                          POST /internal/v1/reply   POST /internal/v1/messages
                          (incoming message)         GET  /internal/v1/status
                          X-Bridge-Token auth         (outgoing / status)
                                              │  │
                                              ▼  │
                                         bot-worker (Node, 183 lines,
                                         stateless HTTP→CLI wrapper)
                                              │
                                    execFile(python -m digital_bast.bot.*)
                                              │
                                              ▼
                                   digital-bast Python app
                                   (all actual bot logic lives here)
```

- **`wa-session`** (image `digital-bast-whatsmeow-session`, container port 8090 for
  setup, some other port for the JSON API): the only thing holding a live WhatsApp
  connection. Auth store: SQLite at `/data/auth-whatsmeow` (bind-mounted, this is what
  the disk-full error corrupted). Exposes, for the Python app to call:
  - `GET /internal/v1/status` → `{connection, me, qrDataUrl, pairingCode}`
    (`digital_bast/infrastructure/whatsapp_outbound.py::BotBridgeWhatsAppOutboundGateway.get_status`)
  - `POST /internal/v1/messages` body `{jid, text, request_id}` → `{status: "sent",
    provider_message_id}` (`...whatsapp_outbound.py::BotBridgeWhatsAppOutboundGateway.send`)

  And *calls out* to `bot-worker` when a WhatsApp message arrives:
  - `POST /internal/v1/reply` on `bot-worker`, header `X-Bridge-Token` (shared secret,
    `sync_ingest_token` file), body one of:
    - `{kind: "text", text, jid?, channel?}` — a text message (DM or group)
    - `{kind: "evidence", jid, filePath, caption}` — an image/file attachment
    - response: `{ok: bool, text: string}` — `text` is what wa-session should send back.

- **`bot-worker`** (image `digital-bast-bot-worker`, Node.js, `server.js` — the *entire*
  service is 183 lines, see `/opt/digital-bast/bot-worker/server.js` in the running
  container): holds no WhatsApp state at all. Its only job is mapping that
  `/internal/v1/reply` payload to a CLI invocation:
  - `{kind:"evidence"}` → `python -m digital_bast.bot.dm_workflow evidence ...`
  - `{kind:"text", channel:"dm"}` → `python -m digital_bast.bot.dm_entry reply --text ... --jid ...`
  - `{kind:"text"}` (group) → `python -m digital_bast.bot.group_entry reply --text ...`
  - anything else → falls through to the general `digital-bast` CLI.

  It shells out via `execFile`, captures stdout, returns `{ok, text: stdout}`. Comment in
  the source is explicit about *why* it's built this way: "Stateless HTTP wrapper around
  the `digital-bast` CLI. Holds no WhatsApp state at all... so rebuilding/recreating this
  on every deploy... never touches the live session." That property must be preserved by
  whatever replaces `wa-session` — deploys of the bot's *logic* should never require
  touching (and risking) the live WhatsApp session.

- **Python app** (`digital_bast.bot.*`): all actual command parsing, BAST-generation
  triggering, evidence handling, etc. Not in scope for this migration at all.

### Why this matters for the migration

The contract surface is exactly **3 endpoints, all small, already precisely typed** (see
above). A whatsapp-web.js-based replacement for `wa-session` only needs to:
1. Implement `GET /internal/v1/status` and `POST /internal/v1/messages` the same shape.
2. Call `bot-worker`'s existing `POST /internal/v1/reply` (unchanged) when a message
   arrives, using the same `X-Bridge-Token` auth.

**`bot-worker` and the entire Python app need zero code changes.** This is a
single-service swap, not a system-wide migration — worth confirming to whoever picks
this up, since it's easy to assume (wrongly) that "rewrite the WhatsApp bot" touches
everything.

## Proposed design for the replacement `wa-session`

- **Runtime**: Node.js + [whatsapp-web.js](https://wwebjs.dev/) + Puppeteer (Chromium).
  `bot-worker` is already Node, so this keeps the bot stack to two languages (Node +
  Python) instead of three (Go + Node + Python) — a real simplification, and makes it
  plausible to eventually fold `wa-session` and `bot-worker` into one process if desired
  (not proposed here — keep them separate for the deploy-isolation property above unless
  there's a specific reason to merge).
- **Session persistence**: whatsapp-web.js's `LocalAuth` strategy persists Chromium's
  own profile directory (cookies/localStorage the real WhatsApp Web page uses) rather
  than a custom SQLite auth store. Needs its own bind-mounted volume, sized generously
  (a real Chromium profile is larger than whatsmeow's SQLite file — check actual size
  after a burn-in period before finalizing the volume/quota, and monitor disk headroom
  proactively this time, ideally with an actual alert rather than discovering it via a
  production outage as happened 2026-09-02).
- **Pairing flow equivalent**: whatsapp-web.js emits a `qr` event with the raw QR
  payload string on first launch / after a forced logout — render it the same way the
  current `/setup/status` page does (a `data:image/png;base64,...` `<img>`, using any QR
  encoding library) behind the same operator-triggered, not-internet-exposed pattern
  (`127.0.0.1`-only bind). Preserve the "automatic pairing blocked after permanent
  disconnect, explicit operator action required" safety behavior — don't auto-retry
  pairing in a loop after a logout; that's a good guard against silently spamming
  pairing attempts if something is actually wrong.
- **Resource footprint / isolation**: this is the one place this migration meaningfully
  changes the operational profile. whatsmeow is a lightweight native-protocol client —
  no browser at all. whatsapp-web.js needs a **persistent Chromium instance running
  24/7** (not a burst like BAST PDF rendering, which only spins up Chromium per
  generation). Reuse the isolation pattern just built for `bast-renderer` (see
  `compose.yaml`, service `bast-renderer`, and `render_worker_asgi.py`) — its own
  container, `read_only`, `shm_size`, `tmpfs` for `/tmp`, `cap_drop: ALL` — so a WhatsApp
  Chromium hang/leak can't affect other services the way the BAST render process did on
  2026-09-03 before that isolation existed. Budget CPU/memory with the *standing* cost
  in mind, not a burst cost: a permanently-running Chromium tab is lighter than a 126-page
  PDF render, but it never releases the memory back the way a per-request render does.
  Plan for steady-state memory (measure after a few days uptime, not just at startup)
  rather than assuming a render-style peak-then-idle pattern.
- **Message send/receive mapping**:
  - Outgoing (`POST /internal/v1/messages` → whatsapp-web.js `client.sendMessage(jid,
    text)`): straightforward.
  - Incoming (whatsapp-web.js `client.on('message', ...)` → `POST bot-worker/internal/v1/reply`):
    map the incoming message event to the same `{kind:"text"|"evidence", text, jid,
    channel}` shape `bot-worker` already expects — `channel` presumably distinguishes DM
    vs group (check `dm_entry.py` / `group_entry.py` for the exact expected values before
    implementing, this doc doesn't pin that down).
  - Evidence/attachments: whatsapp-web.js's `message.downloadMedia()` gives you the file
    bytes directly (no separate download step); write to the same shared volume
    `bot-worker`/the Python app expects (`filePath` in the `kind:"evidence"` payload) —
    check `_exports_directory()`/`BOT_DATA_DIR` conventions in `operations.py` for the
    expected path shape.

## Suggested rollout approach

**Status 2026-09-03**: step 1 is scaffolded and technically smoke-tested (see
`whatsapp-web-session/README.md`) — the isolated container builds, Chromium/Puppeteer
launch cleanly under the same read-only/cap-drop/non-root isolation as `bast-renderer`,
and the full HTTP contract (`/health`, `/ready`, `/internal/v1/status`,
`/internal/v1/messages`, auth, outbound idempotency) round-trips correctly against a
stub bot-worker. **Not yet done: pairing against a real (test) WhatsApp number** — that
needs a phone in hand, which is the next step. Building the image plus its `node_modules`
consumed roughly 2.7GB of the host's disk (down to 8.3GB free from 11GB, on an already
89%-full disk) — worth keeping an eye on given the incident that started this migration
was disk exhaustion; `docker compose -f whatsapp-web-session/compose.prototype.yaml down
-v` plus removing the two images reclaims it if the prototype is abandoned.

1. **Prototype in isolation first** — a throwaway whatsapp-web.js service against a
   *test* WhatsApp number (not the production one), confirming pairing, send, and
   receive all work end-to-end, before touching anything live.
2. **Implement the 3-endpoint contract** exactly as specified above so it's a drop-in
   replacement for `wa-session` from `bot-worker`'s point of view — no `bot-worker` or
   Python changes needed if the contract is honored precisely.
3. **Run side-by-side before cutover**: stand up the new service under a different
   compose service name, verify its `/internal/v1/status`/`/internal/v1/messages`
   responses match shape, before pointing `bot-worker`'s calls (and the Python app's
   `BOT_BRIDGE_BASE_URL`) at it and retiring the old `wa-session`.
4. **Long-term stability can only be assessed by real usage over days/weeks** — this
   isn't something a same-session test can prove one way or the other regardless of
   which library is used. Don't treat a clean initial pairing + a few test messages as
   validation of the "doesn't get banned" claim; that needs sustained real-world
   operation to actually observe.

## Open questions — resolved 2026-09-03 by reading the actual deployed source

**Local checkout warning confirmed in practice**: root `compose.yaml` here is stale —
it predates both the wa-session/bot-worker split and the bast-renderer isolation, and
still describes a single merged `bot-bridge` service. The container actually running
`wa-session` traces back to `releases/8917ce9a9f1ca0c0029b9a98ac9d53921433daf5-1788328945-423572/`
(via `docker inspect ... com.docker.compose.project.working_dir`), which does have the
split — that release directory is what the rest of this doc and the sections below were
verified against, not root `compose.yaml`. Separately, `bast-renderer` and `web-green`
are currently running from a `docker compose up` invoked directly in the root
project directory (not from any release snapshot) — the deployed system currently has
drift between services deployed via different paths. Worth the team's attention
independent of this migration, but out of scope here.

- **`channel` values (resolved)**: `bot-worker/server.js`'s `cliArgsFor` is exhaustive —
  `channel: "dm"` routes to `digital_bast.bot.dm_entry`; anything else (including
  absent) routes to `digital_bast.bot.group_entry`. `kind: "evidence"` always routes to
  `digital_bast.bot.dm_workflow evidence` regardless of channel. No other channel value
  exists.
- **Group allowlist (resolved — it's not enforced)**: `whatsmeow-session/main.go` defines
  `isAllowedGroup`/`allowedGroups()`, but grepping the whole package, the message path
  (`bridge.go handleGroup`) never calls it — it's only used to pre-check checkboxes on
  the setup page. `wa-session/README.md` (the predecessor Baileys implementation, kept
  as rollback data) says this in writing: *"`BOT_ALLOWED_GROUPS` and the old `/allow`
  setup action are no longer used. The policy is intentionally all joined groups +
  explicit mention/trigger."* So the replacement doesn't need an allowlist either —
  building one would be adding scope the real system doesn't have.
- **Parallel-run vs. hard cutover**: still open, deferred until the prototype
  (`whatsapp-web-session/`) is validated against a real test number — see that
  directory's README for current status.

### Scope correction: it's not just 3 endpoints

Reading `whatsmeow-session/bridge.go` and `helpers.go` directly (2,870 lines total
across the Go package) surfaced real behavior living in the transport layer that the
original "3 endpoints, already precisely typed" framing above undersold. A faithful
replacement also needs:

- A per-DM-JID digit-shortcut **menu store** (numbered menu replies expire after 15
  minutes or get superseded by the next non-interactive reply).
- Two JSON **reply envelopes** bot-worker's text response can carry: `{kind:
  "interactive", ...}` (rendered as a numbered/bulleted menu) and `{kind: "file", ...}`
  (sent as media/document instead of text).
- A **wait-notice**: if bot-worker takes longer than `BOT_WAIT_NOTICE_DELAY_MS` (default
  2500ms) to answer something that doesn't look like idle chat, send a "tunggu sebentar"
  placeholder reply first.
- **Quoting** the triggering message on every reply.
- **Export-file cleanup only after a confirmed send** (kept on failure, for retry/
  diagnosis); evidence temp files are always cleaned up once the worker call completes.
- An **operator-action-required latch**: on a permanent logout/ban, persist a marker
  file and refuse to auto-restart pairing until an operator explicitly acts — this is
  the concrete guard against the "rapid reconnect gets the session revoked" failure
  mode, and it's implemented as real state (survives a process restart), not just a
  comment.
- **Outbound idempotency**: `POST /internal/v1/messages` dedupes by `request_id` —
  a retry with the same `{jid,text}` replays the cached result; a retry with a
  different `{jid,text}` under the same `request_id` is rejected as a conflict (HTTP
  409). Not mentioned in the original endpoint summary above.

All of the above is now ported into `whatsapp-web-session/` (see its README for exact
status) rather than left as a second design pass.

### New open question this research surfaced (not resolvable by reading code)

whatsmeow needs `identity.go`'s `canonicalDMIdentity` because WhatsApp's multi-device
protocol can address a DM sender by a "LID" (linked identity) instead of their phone
number, and the bridge has to resolve one to the other for a stable per-user identity.
Whether whatsapp-web.js — which drives the real web.whatsapp.com client rather than
implementing the protocol itself — ever surfaces that same split for a 1:1 chat is
**not yet confirmed**, since this is a WhatsApp-side identity feature, not a
whatsmeow-specific one. The prototype uses `message.author || message.from` as a
best-effort stand-in; needs validation against a real paired account before being
trusted for menu-state or the `jid` field sent to bot-worker.
