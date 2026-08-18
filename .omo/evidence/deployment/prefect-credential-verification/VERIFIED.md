# Prefect credential direct verification

Verdict: **PASS**.

- Read the active secret file in memory from
  `/home/debian/script/digital-bast-v2/secrets/prefect_api_auth`.
- Confirmed mode `0640` and exactly two non-empty `username:password` parts.
- Sent a loopback `POST /api/deployments/filter` request without authentication: HTTP 401.
- Sent the same request using Basic Auth derived in memory from the active secret: HTTP 200.
- No credential value was written to this evidence directory; observables are deliberately redacted.
- Closed the SSH control master and removed its temporary socket directory.

Artifacts:

- `direct-verification.txt`: direct remote validation, exit 0.
- `cleanup.txt`: temporary SSH cleanup, exit 0.
