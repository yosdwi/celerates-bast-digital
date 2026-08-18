# BAST Bot bridge

WhatsApp (Baileys) bridge plus a small setup page. It pairs the bot number,
listens in allowlisted groups and forwards each mention to
`digital-bast bot-reply --text "<message>"`. Every business rule stays in the
Python CLI; this process only moves text.

It runs on the **host**, next to the compose project, because
`digital-bast system-status` shells out to `docker compose ps`. Do not put it in
a container with the Docker socket mounted.

## Run

```bash
cd bot-bridge
npm install
BAST_CLI="uv run digital-bast" npm start        # local
BAST_CLI="digital-bast" npm start               # production (CLI installed on PATH)
```

Open <http://127.0.0.1:8090>:

1. Scan the QR with the dedicated bot number (WhatsApp → Linked devices).
2. Invite the number to the group, reload the page, tick the group, Save.
3. Use "Uji perintah" to run a command without WhatsApp.

Session credentials live in `bot-bridge/auth/` — back them up and the bot
reconnects without a new scan. Delete that directory to force re-pairing.
The allowlist lives in `bot-bridge/data/config.json` (or `BOT_ALLOWED_GROUPS`).

## Local end-to-end run

```bash
cp .env.example .env      # then replace the /run/secrets/* paths with real values
uv sync
cd bot-bridge && npm install
BAST_CLI="uv run digital-bast" npm start
```

For a laptop run the CLI needs direct values instead of container secret files —
remove the `*_FILE` lines from `.env` and set at least:

```bash
APP_DATABASE_DSN=postgresql://user:pass@127.0.0.1:5432/digital_bast_app
NOCODB_DATABASE_DSN=postgresql://user:pass@nocodb-host:5432/nocodb
NOCODB_BASE_ID=pc38r6u1npuq0ul
```

Without them every business command exits `2` with
`application settings are invalid; check .env and the secret files`, and the bot
replies with that same line instead of a stack trace. `system status` still works
without any database because it only reads `docker compose ps`.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_SETUP_HOST` / `BOT_SETUP_PORT` | `127.0.0.1` / `8090` | Setup page bind address. Keep it on loopback and reach it over SSH tunnel in production. |
| `BOT_ALLOWED_GROUPS` | empty | Extra group JIDs, comma separated. |
| `BAST_CLI` | `digital-bast` | Command used to run the CLI. |
| `BAST_CLI_TIMEOUT_MS` | `180000` | Hard timeout per command. |
| `BOT_AUTH_DIR` / `BOT_DATA_DIR` | `./auth` / `./data` | Session and allowlist storage. |

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
WorkingDirectory=/opt/digital-bast/bot-bridge
Environment=BAST_CLI=digital-bast
ExecStart=/usr/bin/node server.js
Restart=always
User=digital-bast
```
