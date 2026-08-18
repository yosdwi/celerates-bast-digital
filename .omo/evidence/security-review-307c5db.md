# Security review: 307c5dbf972990321d8f63c8d269910e76e3237f

## Verdict

**PASS** — blocker severity: **none**.

Reviewed exact SHA `307c5dbf972990321d8f63c8d269910e76e3237f` and reproduced the security-relevant claims for the `HEAD~1..HEAD` delta.

## Scope and findings

- The commit changes exactly `.env.example`, `compose.yaml`, `docs/local-development.md`, and `tests/ops/prefect-ui-url.sh`.
- `PREFECT_SERVER_UI_API_URL` is browser-visible routing configuration, not a credential. Rendering Compose with `https://prefect.example.com/api` sets it only on `prefect-server` and `prefect-services`.
- The change does not alter the Prefect listener, published host binding, Cloudflare configuration, or authentication configuration. `prefect-server` remains published on host IP `127.0.0.1`; `PREFECT_API_AUTH_STRING_FILE` and `PREFECT_SERVER_API_AUTH_STRING_FILE` remain backed by `/run/secrets/prefect_api_auth`.
- Public runtime evidence shows protected endpoints return HTTP 401 without authorization and HTTP 200 with authorization. Browser evidence shows the dashboard and five deployments after the complete `username:password` value is entered in Prefect's single login field. The unauthenticated health endpoint returning HTTP 200 is consistent with health probing and does not expose protected deployment data.
- The targeted test was reproduced locally: `sh tests/ops/prefect-ui-url.sh` printed `Prefect UI API URL checks passed` and exited 0. Rendered configuration confirmed the configured public URL on exactly two services and retained the loopback-only Prefect host port.
- The commit diff contains only secret-file paths and credential-format documentation; it contains no raw credential, token, authorization header value, private key, or private environment value.
- Reviewed text artifacts under `.omo/evidence/deployment/prefect-ui-fix/` and `.omo/evidence/deployment/prefect-credential-verification/` for Basic/Bearer header values, URL userinfo, JWTs, and private keys. No such value was found. Credential verification artifacts explicitly redact values.

## Evidence inspected

- `git diff --no-ext-diff --unified=80 HEAD~1..HEAD`
- `.omo/evidence/deployment/prefect-ui-fix/12-browser-deployments.txt`
- `.omo/evidence/deployment/prefect-ui-fix/15-local-verification.txt`
- `.omo/evidence/deployment/prefect-ui-fix/03-local-public-api.txt`
- `.omo/evidence/deployment/prefect-ui-fix/04-curl-public-api.txt`
- `.omo/evidence/deployment/prefect-ui-fix/13-public-api-green.txt`
- `.omo/evidence/deployment/prefect-ui-fix/16-post-report-direct-verification.txt`
- `.omo/evidence/deployment/prefect-ui-fix/17-hook-direct-raw-output.txt`
- `.omo/evidence/deployment/prefect-credential-verification/VERIFIED.md`
- `.omo/evidence/deployment/prefect-credential-verification/direct-verification.txt`
- `.omo/evidence/deployment/prefect-credential-verification/cleanup.txt`
- `.omo/evidence/deployment/prefect-credential-verification/hook-direct-verification-2.txt`

## Non-blocking provenance note

The runtime/deployment evidence is untracked in the reviewed worktree and is not cryptographically bound to the deployed image or CI run. That provenance limitation is pre-existing/outside this delta and does not show a security regression introduced by SHA `307c5dbf972990321d8f63c8d269910e76e3237f`.
