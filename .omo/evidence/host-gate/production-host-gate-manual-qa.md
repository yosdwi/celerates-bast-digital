# Manual QA matrix: production-host gate

Scope: `/mnt/d/Github/celerates/digital-bast/v2-prod`, target host `142.44.242.56`.
All PASS rows point to non-empty artifact `host-gate-observables.md`.

## surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| HG-SSH-22 | host SSH reachability | TCP/SSH | `timeout 12s nc -vz -w 3 142.44.242.56 22` | PASS (TCP accepts) | HG-OBS |
| HG-SSH-TRUE | safe remote probe | SSH | `timeout 12s ssh -o ConnectTimeout=8 -o BatchMode=yes 142.44.242.56 true` | BLOCKED (session reset, exit 255) | HG-OBS |
| HG-HTTPS-ROOT | HTTPS endpoint reachability | HTTPS | `timeout 12s curl -sS --connect-timeout 3 --max-time 8 -o /dev/null -w ... https://142.44.242.56/` | BLOCKED (TLS timeout, exit 28) | HG-OBS |
| HG-HTTPS-READY | public readiness | HTTPS | same bounded curl to `https://142.44.242.56/health/ready` | BLOCKED (TLS timeout, exit 28) | HG-OBS |
| HG-NOCODB | configured NocoDB endpoint | HTTPS/no-auth | bounded curl to repository value `https://nocodb.example.com/` | BLOCKED (placeholder DNS failure; not production endpoint) | HG-OBS |
| HG-PG-5432 | PostgreSQL exposure check | TCP | `timeout 12s nc -vz -w 3 142.44.242.56 5432` | PASS (not publicly reachable; timeout) | HG-OBS |
| HG-PREFLIGHT | documented server preflight | repository shell | `SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s scripts/preflight.sh` | BLOCKED (missing `./secrets/postgres_password`, exit 78) | HG-OBS |
| HG-COMPOSE-CONFIG | documented Compose validation | repository shell | `SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s docker compose --profile blue config --quiet` | PASS (exit 0; syntax/config only) | HG-OBS |
| HG-DEPLOY-DRY | documented deployment dry-run | repository shell | `SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local timeout 30s scripts/deploy.sh --dry-run` | BLOCKED (same missing secret, exit 78) | HG-OBS |
| HG-ROLLBACK-DRY | documented rollback dry-run | repository shell | `timeout 30s scripts/rollback.sh --dry-run` | PASS (local print path only; no remote/health proof) | HG-OBS |
| HG-ADV-OPS | repository adversarial safeguards | repository shell | `SECRETS_GID=$(id -g) timeout 20s tests/ops/adversarial.sh` | PASS (`adversarial checks passed`, exit 0) | HG-OBS |

## adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV-01 | HG-SSH-TRUE | dirty_worktree | Record status and refuse deployment from a dirty checkout. | FAIL gate (status is dirty; all product files untracked) | HG-OBS |
| ADV-02 | HG-DEPLOY-DRY | stale_state | Require immutable image/deployment metadata and live service state. | FAIL gate (only `digital-bast:local`; image absent; no compose services) | HG-OBS |
| ADV-03 | HG-SSH-TRUE/HG-HTTPS-READY | hung_or_long_commands | Every network probe has hard timeout and reports nonzero exit on timeout/reset. | PASS | HG-OBS |
| ADV-04 | HG-DEPLOY-DRY | misleading_success_output | Require exit code plus actual endpoint/remote observable; dry-run text alone is insufficient. | FAIL gate (only rollback dry-run text; SSH/HTTPS do not complete) | HG-OBS |
| ADV-05 | HG-ROLLBACK-DRY | repeated_interruptions | Failed probes leave no probe process or held deployment lock. | PASS (post-probe `ps` empty for ssh/nc/curl; lock non-held and QA file removed) | HG-OBS |
| ADV-06 | — | malformed_input | Not applicable: no malformed deployment input was supplied; changing arguments would be outside the production-host gate. | not_applicable | HG-OBS |
| ADV-07 | — | prompt_injection | Not applicable: no untrusted prompt/content was fed to deployment scripts. | not_applicable | HG-OBS |
| ADV-08 | — | cancel_resume | Not applicable: no deployment was started or cancelled; host session failed before execution. | not_applicable | HG-OBS |
| ADV-09 | — | flaky_tests | Not applicable: this gate uses bounded shell/network probes, not a test retry policy. | not_applicable | HG-OBS |

## artifactRefs

| id | kind | description | path |
|---|---|---|---|
| HG-OBS | transcript | Redacted host connectivity, preflight, image/state, prerequisite, and cleanup observables | `.omo/evidence/host-gate/host-gate-observables.md` |

## Gate verdict

**BLOCKED — do not deploy.** The exact external blocker is that the required SSH `true` probe is
reset by `142.44.242.56` after TCP port 22 accepts, so no documented remote preflight or
deployment can be executed. Independent local blockers (dirty checkout, absent production
secrets, missing immutable image, absent NocoDB endpoint, and no evidence of disk/credential/
staging-shadow/backup-restore/rollback prerequisites) also fail the documented gates. No
deployment command was run against the host and no destructive change was made.

## Direct-target follow-up

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| HG-SSH-DEBIAN | direct production SSH authorization | SSH | `ssh -o ConnectTimeout=10 -o ConnectionAttempts=1 -o StrictHostKeyChecking=accept-new debian@142.44.242.56 true`, then explicit `-i ~/.ssh/miropr_deploy.pem -o IdentitiesOnly=yes -o BatchMode=yes` retry | BLOCKED (KEX succeeds; explicit RSA key rejected; exit 255) | HG-OBS |

Direct-target stop condition is met: the exact `debian@142.44.242.56` attempt failed twice, with
the protocol stage identified in the redacted verbose transcript. Remote inspection and deploy
were not attempted.

Final configured-identity check: v1 `.env` has no SSH user/key/path setting, and repository
workflow values are unresolved GitHub vars/secrets. No additional SSH attempt was made. Missing
credential: authorized private key/`DEPLOY_KEY` for `debian` and the production `DEPLOY_PATH`.
