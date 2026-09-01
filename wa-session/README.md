# wa-session

WhatsApp (Baileys) session holder plus a small setup page. It pairs the bot
number, listens in every group the bot has joined, and forwards a message to
**bot-worker** (`../bot-worker/`) only when the bot is explicitly mentioned or
called with a supported trigger. It has no `digital-bast` CLI dependency itself
and is not built from the app image, on purpose: recreating this container drops
the live WhatsApp connection, and WhatsApp's own anti-abuse system will revoke
the session after a few rapid reconnects. Keeping this image minimal and
independent of app-only changes is what lets `bot-worker` redeploy on every
release without ever touching this process. See the repo root's split plan /
`docs/bast-bot.md` for the full rationale.

## Run

```bash
cd wa-session
npm install
BOT_WORKER_BASE_URL="http://127.0.0.1:8091" npm start
```

`bot-worker` must be reachable at `BOT_WORKER_BASE_URL` for replies to work;
the setup page's QR/pairing and `/try` still work without it, but "Uji perintah"
and real messages will report `bot-worker unreachable`.

Open <http://127.0.0.1:8090>:

1. Scan the QR (or enter the pairing code shown alongside it via
   `BOT_PAIRING_NUMBER`) with the dedicated bot number (WhatsApp → Linked
   devices → Link with phone number).
2. Invite the number to any group where it should be usable. No group allowlist
   configuration is required: all joined groups are eligible, but the bot still
   ignores ordinary conversation unless it is mentioned/triggered.
3. Use "Uji perintah" to run a command without WhatsApp (round-trips through
   `bot-worker` exactly like a real message).

Session credentials live in `BOT_AUTH_DIR` (default `./auth`) — back them up
and the bot reconnects without a new scan. Delete that directory only when an
intentional re-pair is required.

## Local end-to-end run

`wa-session` itself needs no database or app settings at all -- only
`bot-worker` does (it runs the application entrypoints). See
`../bot-worker/README.md` for getting a real reply chain working locally;
`wa-session` just needs `bot-worker` reachable at `BOT_WORKER_BASE_URL`.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_SETUP_HOST` / `BOT_SETUP_PORT` | `127.0.0.1` / `8090` | Setup page bind address. Keep it on loopback and reach it over SSH tunnel in production. |
| `BOT_WORKER_BASE_URL` | `http://bot-worker:8091` | Where each qualifying message is sent for a reply. |
| `BOT_PAIRING_NUMBER` | empty | Digits-only international format; requests a "Link with phone number" code instead of relying on QR alone. Only takes effect while unregistered. |
| `BOT_AUTH_DIR` / `BOT_DATA_DIR` | `./auth` / `./data` | Session storage and temporary evidence-upload storage. |
| `SYNC_INGEST_TOKEN_FILE` / `BOT_BRIDGE_TOKEN_FILE` | `/run/secrets/sync_ingest_token` | Shared bearer token for the internal HTTP calls to/from `bot-worker` and the web app's status proxy. |

`BOT_ALLOWED_GROUPS` and the old `/allow` setup action are no longer used. The
policy is intentionally all joined groups + explicit mention/trigger.

## Triggers

The bot is available in every group it has joined, but it responds only when it
is actually mentioned or the message uses a supported trigger such as
`@conform`, `@BAST Bot`, or `!bast`. Direct messages use the separate Talent/PMO
DM workflows.

```text
@conform cek status tasklist iot
@conform siapa developer yang evidence-nya masih kurang agustus 2026?
@BAST Bot export attendance developer 1 sampai 31 Agustus
@BAST Bot generate BAST 1 sampai 31 Juli
@BAST Bot system status
```

## Keep alive

```bash
# systemd unit, adjust paths
[Service]
WorkingDirectory=/opt/wa-session
Environment=BOT_WORKER_BASE_URL=http://127.0.0.1:8091
ExecStart=/usr/bin/node server.js
Restart=always
User=digital-bast
```
