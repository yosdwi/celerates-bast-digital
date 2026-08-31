# Whatsmeow session transport

This directory is the replacement transport for the existing `wa-session/` Baileys bridge.
It deliberately keeps the same backend contracts instead of moving business rules into Go:

- inbound text/DM/group commands -> `bot-worker POST /internal/v1/reply`
- inbound evidence -> the same bot-worker evidence request
- backend notifications -> `POST /internal/v1/messages` with `x-bridge-token`
- setup/status -> port 8090 (`/`, `/health`, `/internal/v1/status`)
- interactive backend envelopes remain a numbered text fallback, so protocol experiments cannot silently drop a business reply.

## Session storage

Whatsmeow state is stored in SQLite at `${BOT_AUTH_DIR}/session.db`. The database is the durable
cryptographic session store; never put it in `/tmp`, never share it between two running processes,
and never delete it automatically on disconnect. `StreamReplaced`, `LoggedOut`, temporary-ban and
client-outdated events are logged distinctly to make repeated session failures diagnosable.

Baileys auth files are not compatible with whatsmeow. The first cutover therefore requires one
controlled new pairing. Stop the old Baileys service before pairing this service, and keep exactly
one process connected with the new session.

## Build

Go 1.26+ and a C compiler are required because the durable SQLite driver uses CGO.

```bash
go test ./...
go build -trimpath -o digital-bast-whatsmeow .
```

## Runtime environment

The existing bridge variables are intentionally reused:

- `BOT_SETUP_HOST`
- `BOT_SETUP_PORT`
- `BOT_AUTH_DIR`
- `BOT_DATA_DIR`
- `BOT_ALLOWED_GROUPS`
- `BOT_WORKER_BASE_URL`
- `BOT_BRIDGE_TOKEN_FILE` / `SYNC_INGEST_TOKEN_FILE`
- `BOT_PAIRING_NUMBER`
- `BOT_WAIT_NOTICE_DELAY_MS`
- `BOT_WHATSMEOW_LOG_LEVEL`

The service fetches WhatsApp Web's current version before connecting and then lets whatsmeow own
normal reconnects. A permanent logout does not delete the auth DB.

## Cutover safety

Merging this directory does not cut production over from Baileys. The production host currently has
its own service topology and must be audited before changing it. During a controlled cutover:

1. keep a backup of the current Baileys auth directory;
2. stop the old WhatsApp transport so only one companion client is active;
3. start whatsmeow with a separate persistent `BOT_AUTH_DIR`;
4. pair once;
5. verify `/health`, DM, group, evidence and outbound notification flows;
6. never loop pairing/restarts when WhatsApp reports a permanent disconnect.
