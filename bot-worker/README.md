# bot-worker

Stateless HTTP wrapper around the `digital-bast` CLI. Receives each WhatsApp
message from **wa-session** (`../wa-session/`) over HTTP and shells out to
`digital-bast bot-reply` / `digital-bast bot-evidence` exactly as the combined
bridge did before the split -- the only thing that changed is which process
does it. Holds no WhatsApp session state, so it rebuilds and recreates on
every deploy (same as `scripts/deploy.sh` did for the combined service
before), harmlessly: there's no live socket here to interrupt.

## Run

```bash
cd bot-worker
npm install
cp ../.env.example ../.env      # then replace the /run/secrets/* paths with real values
BAST_CLI="uv run digital-bast" npm start        # local, CLI via uv
BAST_CLI="digital-bast" npm start               # production, CLI on PATH
```

For a laptop run the CLI needs direct values instead of container secret
files -- remove the `*_FILE` lines from `.env` and set at least:

```bash
APP_DATABASE_DSN=postgresql://user:pass@127.0.0.1:5432/digital_bast_app
NOCODB_DATABASE_DSN=postgresql://user:pass@nocodb-host:5432/nocodb
NOCODB_BASE_ID=pc38r6u1npuq0ul
```

Without them every business command exits `2` with `application settings are
invalid; check .env and the secret files`, and the HTTP reply carries that
same line instead of a stack trace.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_WORKER_HOST` / `BOT_WORKER_PORT` | `0.0.0.0` / `8091` | Bind address. Only reachable internally -- no host port mapping in production. |
| `BAST_CLI` | `digital-bast` | Command used to run the CLI. |
| `BAST_CLI_TIMEOUT_MS` | `180000` | Hard timeout per command. |
| `SYNC_INGEST_TOKEN_FILE` / `BOT_BRIDGE_TOKEN_FILE` | `/run/secrets/sync_ingest_token` | Shared bearer token wa-session must present as `X-Bridge-Token`. |

## API

`POST /internal/v1/reply` (requires `X-Bridge-Token`):

```json
{"kind": "text", "text": "status 1 sampai 31 Agustus"}
{"kind": "text", "text": "halo", "jid": "628123@s.whatsapp.net", "channel": "dm"}
{"kind": "evidence", "jid": "628123@s.whatsapp.net", "filePath": "/data/evidence-uploads/1-a.jpg", "caption": "bukti kerja"}
```

Returns `{"ok": true, "text": "..."}` or `{"ok": false, "text": "..."}`, the
same shape the combined bridge's internal `runCli` helper used to produce.

`GET /health` -> `{"ok": true}` -- simple liveness, no session to report.
