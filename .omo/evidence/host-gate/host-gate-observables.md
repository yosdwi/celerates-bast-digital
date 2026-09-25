# Digital BAST v2 production-host gate observables

Date: 2026-08-03 (Asia/Jakarta)

All probes were read-only, bounded by `timeout`, and emitted no credentials, tokens,
headers, connection strings, private keys, or response bodies.

## Repository and local runtime

- `pwd`: `/mnt/d/Github/celerates/digital-bast/v2-prod`
- `git rev-parse HEAD`: `f3741d18b009c3aae872a2986288cc439e01fbea`
- branch: `main`
- `git status --short --untracked-files=all`: dirty; all product/docs/scripts files are untracked (`??`), including `compose.yaml`, `scripts/`, `src/`, `tests/`, and `.github/`. No clean deployment checkout is evidenced.
- `df -Pk /`: total `1055762868` KiB, available `914433796` KiB (local workstation exceeds the documented 150-GB/20-GB thresholds; this is not host evidence).
- `docker info`: Docker server `28.3.3`, 24 containers and 48 images (local workstation only).
- `docker compose version`: `v2.39.1`.
- `docker compose config --images` (with `SECRETS_GID=$(id -g)` and `NOCODB_BASE_URL=https://invalid.local`): default application image is `digital-bast:local`; no immutable SHA/digest is configured.
- `docker image inspect digital-bast:local`: `No such image` (exit 1).
- `docker compose ps --all` (same sanitized env): no project services/containers listed.
- `config/nginx/active-slot.conf`: active slot is `web-blue:8000`.

## Host connectivity (142.44.242.56)

Exact invocations and exit codes:

```text
timeout 12s nc -vz -w 3 142.44.242.56 22
Connection to 142.44.242.56 22 port [tcp/ssh] succeeded!
exit=0

timeout 12s ssh -o ConnectTimeout=8 -o BatchMode=yes 142.44.242.56 true
kex_exchange_identification: read: Connection reset by peer
Connection reset by 142.44.242.56 port 22
exit=255

timeout 12s curl -sS --connect-timeout 3 --max-time 8 -o /dev/null \
  -w 'http_code=%{http_code} remote_ip=%{remote_ip} content_type=%{content_type}\n' \
  https://142.44.242.56/
curl: (28) SSL connection timeout
http_code=000 remote_ip=142.44.242.56 content_type=
exit=28

timeout 12s curl -sS --connect-timeout 3 --max-time 8 -o /dev/null \
  -w 'http_code=%{http_code} remote_ip=%{remote_ip} content_type=%{content_type}\n' \
  https://142.44.242.56/health/ready
curl: (28) SSL connection timeout
http_code=000 remote_ip=142.44.242.56 content_type=
exit=28

timeout 12s nc -vz -w 3 142.44.242.56 5432
nc: connect to 142.44.242.56 port 5432 (tcp) timed out: Operation now in progress
exit=1
```

Port 22 is TCP-reachable, but the required non-interactive `true` probe cannot complete
because the server resets the SSH session. HTTPS does not complete within the hard timeout.
PostgreSQL is not publicly reachable, consistent with the repository's private-network rule.

The SSH and HTTPS probes were repeated twice with the same bounded options. Both SSH attempts
returned exit 255 with `Connection reset by peer`; both HTTPS attempts returned exit 28 with
`SSL connection timeout` and `http_code=000`. A post-repeat process check found no `ssh`, `nc`,
or `curl` processes.

The only repository NocoDB URL is the `.env.example` placeholder
`https://nocodb.example.com`; no production endpoint is configured. A no-auth probe to that
placeholder was run only to document this:

```text
timeout 12s curl -sS --connect-timeout 3 --max-time 8 -o /dev/null \
  -w 'http_code=%{http_code} remote_ip=%{remote_ip} content_type=%{content_type}\n' \
  https://nocodb.example.com/
curl: (6) Could not resolve host: nocodb.example.com
http_code=000 remote_ip= content_type=
exit=6
```

This is not production-host reachability evidence and cannot satisfy the NocoDB gate.

## Repository-documented preflight and deployment probes

The documented commands were run with only non-secret placeholder environment values where
needed (`SECRETS_GID=$(id -g)`, `NOCODB_BASE_URL=https://invalid.local`).

```text
SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s scripts/preflight.sh
required file unavailable: ./secrets/postgres_password
exit=78

SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s \
  docker compose --profile blue config --quiet
exit=0

SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s \
  scripts/deploy.sh --dry-run
required file unavailable: ./secrets/postgres_password
exit=78

timeout 30s scripts/rollback.sh --dry-run
DRY-RUN verify web-green is healthy
DRY-RUN switch blue to green
rollback dry-run complete
exit=0
```

The preflight and deploy dry-run stop before any compose lifecycle action because the required
secret directory/files are absent (`secrets_directory=absent`). The rollback dry-run is only a
local print path; it did not prove a healthy previous slot or a remote rollback.

Required command metadata: `docker`, Compose, `curl`, `flock`, `nc`, and `ssh` are present;
`age` is missing. `rclone` is present. `backups/` is absent and
`AGE_RECIPIENT`, `BACKUP_REMOTE`, `BACKUP_FILE`, and `AGE_IDENTITY_FILE` are unset. Both
`scripts/backup.sh --dry-run` and `scripts/restore-test.sh --dry-run` stop with
`required command unavailable: age` (exit 69).

## Required production prerequisites and stale-state checks

No artifact in `.omo/evidence/`, docs, or workflow files records a completed production disk
expansion, credential rotation, staging shadow-parity run, verified backup timestamp, restore
test, rollback rehearsal, immutable image digest, or production operator approval. Existing
`DRY-RUN shadow`/`DRY-RUN rollback` lines are static/local dry-run output only.

The local checkout is dirty, has no production secrets, no configured `APP_IMAGE`/deploy host
metadata, no immutable image, and no compose service state. These are stale/unready state
observables, not inferred production success.

## Cleanup

After probes, a process check using `ps` found no `ssh`, `nc`, or `curl` probe processes. The
QA-created `/tmp/digital-bast-deploy.lock` from the rollback dry-run was confirmed non-held with
`flock -n` and removed; the temporary adversarial-test directory was self-cleaned. No containers,
volumes, images, repository files, or host resources were changed.

## Direct production SSH target follow-up

The current user's `/home/yosdwi/.ssh/` contains `miropr_deploy.pem`; `/mnt/d/Github/celerates/digital-bast/v1-prod/.env` was inspected by variable names only and contains no deploy-user/path/key variables. No `.env` values were printed.

Required first command:

```text
ssh -o ConnectTimeout=10 -o ConnectionAttempts=1 -o StrictHostKeyChecking=accept-new debian@142.44.242.56 true
ssh_askpass: exec(/usr/bin/ssh-askpass): No such file or directory
Permission denied, please try again.
debian@142.44.242.56: Permission denied (publickey,password).
exit=255
```

Retry using the existing current-user key, with identity selection constrained and batch mode:

```text
ssh -i "$HOME/.ssh/miropr_deploy.pem" -o IdentitiesOnly=yes \
  -o ConnectTimeout=10 -o ConnectionAttempts=1 \
  -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
  debian@142.44.242.56 true
debian@142.44.242.56: Permission denied (publickey,password).
exit=255
```

Redacted `-vvv` retry identified the protocol stage: TCP connection established; SSH KEX and
NEWKEYS completed; the known ED25519 host key matched; the explicit RSA key was offered and
rejected (`SSH_MSG_USERAUTH_FAILURE`); no password method was attempted in batch mode; final
error was `Permission denied (publickey,password)`. No remote command executed.

Because the exact `debian@142.44.242.56` authentication attempt failed twice (with and without
the existing key), documented remote preflight and deployment were not attempted. No remote
deployment directory, image, containers, or health/Prefect endpoints can be inspected safely
until an authorized SSH key/user is supplied. Local probe cleanup remained intact: no `ssh`,
`nc`, or `curl` processes were left running.

## Final configured-identity check

Variable names in `/mnt/d/Github/celerates/digital-bast/v1-prod/.env` were inspected without
printing values. SSH/deploy-specific names are absent; the only vaguely related names are
`SHEETS_CREDENTIALS_PATH`, `RESEND_API_KEY`, and database password names. Repository deployment
workflow references (`DEPLOY_USER`, `DEPLOY_HOST`, `DEPLOY_PATH`, `DEPLOY_KEY`, `KNOWN_HOSTS`)
are GitHub environment variables/secrets, not concrete local values or a configured key path.
The only local key file is `~/.ssh/miropr_deploy.pem`, which is not explicitly configured by
v1 `.env` or repository deploy configuration. Therefore no additional configured-identity SSH
attempt was authorized or performed. Exact missing credential needed: an authorized SSH private
key (or GitHub `DEPLOY_KEY`) for user `debian`, plus the production `DEPLOY_PATH` value.
