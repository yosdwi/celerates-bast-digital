# creds/

Put credential files here. Everything in this folder is gitignored except this
README and `.gitkeep` — verified with `git check-ignore`, and the repo is
public, so nothing you drop here can be committed by accident.

Expected contents:

| File | What it is | Where to get it |
|---|---|---|
| `service_account.json` | Google service-account key for the IoT sheet | GCP console → project `digital-bast` → IAM → Service Accounts → Keys → Add key (JSON). The previous key is dead (`invalid_grant: Invalid JWT Signature`), so this must be a fresh one. |

The service account needs only **Viewer** access on the spreadsheet — share
the sheet with the account's `client_email`, which is inside the JSON. Read-only
is deliberate: the bridge never writes to the sheet.

Secrets that are single strings (passwords, the ingest token) go in
`bridge/.env`, not here.
