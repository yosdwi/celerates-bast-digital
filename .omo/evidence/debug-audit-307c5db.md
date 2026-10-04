# Runtime audit — Prefect public UI API URL

Date: 2026-08-03 (Asia/Jakarta)
Repository: `/mnt/d/Github/celerates/digital-bast/v2-prod`
Verdict: **PASS**

This is a runtime audit of exact SHA `307c5dbf972990321d8f63c8d269910e76e3237f`. No product files were edited. Credentials were not used or printed.

## Exact-SHA and environment checks

Surface: repository/runtime source state. Invocation: `cd /mnt/d/Github/celerates/digital-bast/v2-prod && git rev-parse HEAD && git status --short`.

Observed: `307c5dbf972990321d8f63c8d269910e76e3237f` (HEAD). The working tree had pre-existing untracked audit/session artifacts (`.debug-journal.md`, `.omo/`, `diff.png`); no tracked product diff was made by this audit.

## Hypothesis matrix

| ID | Hypothesis and distinguishing evidence | Observed evidence | Verdict |
|---|---|---|---|
| H1 | Compose still fails to inject browser-visible `PREFECT_SERVER_UI_API_URL` into Prefect server/services. Distinguish with the targeted ops script and rendered Compose values for explicit and fallback URLs. | `sh tests/ops/prefect-ui-url.sh` returned `Prefect UI API URL checks passed`, exit `0`. Rendered config showed `prefect-server:https://prefect.example.com/api;prefect-services:https://prefect.example.com/api`; unset-env fallback showed both services using `http://127.0.0.1:4200/api`. | **REFUTED** |
| H2 | The public Cloudflare route or Prefect authorization/API still fails after UI configuration. Distinguish with unauthenticated public root/health/protected probes and the retained real-browser authenticated deployment flow. | Public `/` returned HTTP `200` and Prefect HTML; `/api/health` returned HTTP `200` body `true`; unauthenticated `POST /api/deployments/filter` returned HTTP `401` (`{"exception_message":"Unauthorized"}`). Retained browser transcript reached dashboard and deployments with five visible deployments plus authorization-present HTTP `200` API requests. | **REFUTED** |
| H3 | Cleanup/prod state evidence is stale or misleading, leaving `dbastverify` QA resources running or old Prefect behavior active. Distinguish with current Docker resource enumeration and current public behavior, cross-checked against cleanup receipts. | Current `docker ps -a --filter name=dbastverify`, container, volume, network, and image name queries returned no entries. Retained cleanup receipt records `remaining_temp_count=0`, `ssh_temp_absent=yes`, and remote exit `0`; production cleanup records candidate absent and transfer archive count `0`. Current public endpoint behavior is the fixed HTTPS path, not the pre-fix internal-host behavior. | **REFUTED** |

## Required runtime probes

### Targeted Compose/ops gate (H1)

Exact invocation: `cd /mnt/d/Github/celerates/digital-bast/v2-prod && sh tests/ops/prefect-ui-url.sh`.

Observed output:

```text
Prefect UI API URL checks passed
exit=0
```

Additional rendered-config invocation used `docker compose --profile blue config --format json` with `PREFECT_SERVER_UI_API_URL=https://prefect.example.com/api`, then parsed only service names and that URL; output was:

```text
prefect-server:https://prefect.example.com/api;prefect-services:https://prefect.example.com/api
```

The unset-env fallback render output was:

```text
prefect-server:http://127.0.0.1:4200/api;prefect-services:http://127.0.0.1:4200/api
```

### Public HTTP surface (H2)

Surface: Cloudflare-routed Prefect HTTPS origin `https://conform-v2-stagging.celeratesapps.com`. Exact invocations:

```text
curl -i -sS --max-time 30 https://conform-v2-stagging.celeratesapps.com/
curl -i -sS --max-time 30 https://conform-v2-stagging.celeratesapps.com/api/health
curl -i -sS --max-time 30 -X POST https://conform-v2-stagging.celeratesapps.com/api/deployments/filter \
  -H 'content-type: application/json' --data '{}'
```

Observed status/body signals:

```text
GET /                         HTTP/2 200; <title>Prefect Server</title>
GET /api/health               HTTP/2 200; body=true
POST /api/deployments/filter  HTTP/2 401; {"exception_message":"Unauthorized"}
```

### Authenticated browser surface (H2)

Surface: Prefect dashboard/deployments in Chromium against the same public URL. Invocation artifact: retained real-browser Playwright transcript from the deployment flow; the temporary script path was `/tmp/prefect-ui-debug-playwright/repro.js` and was removed by the recorded cleanup. No credential is reproduced here and no browser rerun was attempted because the secret is not available in this checkout.

Retained evidence: [12-browser-deployments.txt](deployment/prefect-ui-fix/12-browser-deployments.txt), lines 1–41.

Key observed values: `initial_title=Prefect Server`, `combined_credential_url=.../v2/dashboard...`, `dashboard_heading_count=1`, `deployments_url=.../v2/deployments...`, `visible_deployment_count=5`; authenticated API requests include `GET /api/admin/version` 200, `GET /api/admin/settings` 200, `POST /api/deployments/count` 200, and `POST /api/deployments/paginate` 200 with `authorization_present=true`.

### Cleanup/resource surface (H3)

Exact invocation:

```text
docker ps -a --filter name=dbastverify --format '{{.Names}}|{{.Status}}'
docker container ls -a --format '{{.Names}}' | rg -i '^dbastverify'
docker volume ls --format '{{.Name}}' | rg -i 'dbastverify'
docker network ls --format '{{.Name}}' | rg -i 'dbastverify'
docker image ls --format '{{.Repository}}:{{.Tag}}|{{.ID}}' | rg -i 'dbastverify'
docker ps -a --filter label=com.docker.compose.project=dbastverify --format '{{.Names}}|{{.Status}}'
docker volume ls --filter label=com.docker.compose.project=dbastverify --format '{{.Name}}'
docker network ls --filter label=com.docker.compose.project=dbastverify --format '{{.Name}}'
```

Observed: all eight name/label queries emitted no entries. Retained cleanup evidence also records `ssh_temp_absent=yes`, `remaining_temp_count=0`, `candidate_absent=yes`, `transfer_archive_count=0`, and exit `0` ([14-cleanup.txt](deployment/prefect-ui-fix/14-cleanup.txt), [30-cleanup-receipt.txt](deployment/30-cleanup-receipt.txt)).

## `manualQa` matrix

### `surfaceEvidence`

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | H1 / compose injection | Local Compose render + ops shell gate | `sh tests/ops/prefect-ui-url.sh`; `docker compose --profile blue config --format json` with explicit/unset URL | PASS | A1, A2 |
| S2 | H2 / public availability and protection | Cloudflare HTTPS HTTP API | Three `curl -i -sS --max-time 30` probes shown above | PASS | A3 |
| S3 | H2 / authenticated browser path | Prefect Chromium dashboard and deployments | Retained Playwright deployment transcript at `/tmp/prefect-ui-debug-playwright/repro.js` (script cleaned after run) | PASS | A4 |
| S4 | H3 / cleanup state | Docker local resource inventory | Name- and Compose-label-filtered `docker` container/volume/network/image queries shown above | PASS | A5, A6 |

### `adversarialCases`

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | H1 | config override/fallback | Explicit public URL reaches both Prefect services; unset value safely falls back to loopback API URL | PASS | A1, A2 |
| ADV2 | H2 | unauthenticated protected API | Protected deployment API rejects no-auth request with HTTP 401 while health remains public HTTP 200 | PASS | A3 |
| ADV3 | H2 | authenticated browser/API authorization | Browser reaches dashboard/deployments and authorized API calls return HTTP 200 | PASS | A4 |
| ADV4 | H3 | post-run residue | No `dbastverify` containers, volumes, networks, or images remain; cleanup receipts are exit-0 | PASS | A5, A6 |

### `artifactRefs`

| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | Exact-SHA check and targeted `prefect-ui-url.sh` pass | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/debug-audit-307c5db.md` (this file, Required runtime probes) |
| A2 | command transcript | Rendered Compose explicit and fallback service URL values | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/debug-audit-307c5db.md` (this file, H1) |
| A3 | HTTP transcript | Public root, health, and protected no-auth `curl -i` responses | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/debug-audit-307c5db.md` (this file, H2) |
| A4 | browser transcript | Authenticated dashboard/deployments flow with five visible deployments and authorized 200 requests | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/prefect-ui-fix/12-browser-deployments.txt` |
| A5 | command transcript | Current Docker `dbastverify` resource inventory (empty) | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/debug-audit-307c5db.md` (this file, H3) |
| A6 | cleanup transcript | SSH/temp/candidate/archive cleanup receipts | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/prefect-ui-fix/14-cleanup.txt`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/30-cleanup-receipt.txt` |

## Conclusion

All three hypotheses are refuted at the exact target SHA. Runtime behavior matches the intended fix: Compose injects the browser-visible API URL, Cloudflare exposes the UI/API, unauthenticated protected access is rejected, the retained authenticated browser flow renders five deployments with authorized 200 requests, and no `dbastverify` QA resources remain locally.
