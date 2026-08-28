# wa-session

WhatsApp (Baileys) session holder plus a small setup page. It pairs the bot
number, listens in allowlisted groups, and for each qualifying message calls
**bot-worker** (`../bot-worker/`) over HTTP to get the reply -- it has no
`digital-bast` CLI dependency itself and is not built from the app image, on
purpose: recreating this container drops the live WhatsApp connection, and
WhatsApp's own anti-abuse system will revoke the session after a few rapid
reconnects. Keeping this image minimal and independent of app-only changes is
what lets `bot-worker` redeploy on every release without ever touching this
process. See the repo root's split plan / `docs/bast-bot.md` for the full
rationale.

## Run

```bash
cd wa-session
npm install
BOT_WORKER_BASE_URL="http://127.0.0.1:8091" npm start
```

`bot-worker` must be reachable at `BOT_WORKER_BASE_URL` for replies to work;
the setup page's QR/pairing and `/allow`/`/try` still work without it, but
"Uji perintah" and real messages will report `bot-worker unreachable`.

Open <http://127.0.0.1:8090>:

1. Scan the QR (or enter the pairing code shown alongside it via
   `BOT_PAIRING_NUMBER`) with the dedicated bot number (WhatsApp → Linked
   devices → Link with phone number).
2. Invite the number to the group, reload the page, tick the group, Save.
3. Use "Uji perintah" to run a command without WhatsApp (round-trips through
   `bot-worker` exactly like a real message).

Session credentials live in `BOT_AUTH_DIR` (default `./auth`) — back them up
and the bot reconnects without a new scan. Delete that directory to force
re-pairing. The allowlist lives in `BOT_DATA_DIR/config.json` (or
`BOT_ALLOWED_GROUPS`).

## Local end-to-end run

`wa-session` itself needs no database or app settings at all -- only
`bot-worker` does (it runs the CLI). See `../bot-worker/README.md` for
getting a real reply chain working locally; `wa-session` just needs
`bot-worker` reachable at `BOT_WORKER_BASE_URL`.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_SETUP_HOST` / `BOT_SETUP_PORT` | `127.0.0.1` / `8090` | Setup page bind address. Keep it on loopback and reach it over SSH tunnel in production. |
| `BOT_ALLOWED_GROUPS` | empty | Extra group JIDs, comma separated. |
| `BOT_WORKER_BASE_URL` | `http://bot-worker:8091` | Where each qualifying message is sent for a reply. |
| `BOT_PAIRING_NUMBER` | empty | Digits-only international format; requests a "Link with phone number" code instead of relying on QR alone. Only takes effect while unregistered. |
| `BOT_AUTH_DIR` / `BOT_DATA_DIR` | `./auth` / `./data` | Session and allowlist storage; evidence uploads land in `BOT_DATA_DIR/evidence-uploads`. |
| `SYNC_INGEST_TOKEN_FILE` / `BOT_BRIDGE_TOKEN_FILE` | `/run/secrets/sync_ingest_token` | Shared bearer token for the internal HTTP calls to/from `bot-worker` and the web app's status proxy. |

## Triggers

The bot answers only in allowlisted groups, and only when it is mentioned or the
message starts with `@BAST Bot` / `!bast`. Direct messages are ignored.

```text
@BAST Bot status 1 sampai 31 Agustus
@BAST Bot export attendance 20 Juli sampai 18 Agustus
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
