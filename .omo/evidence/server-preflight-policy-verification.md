# Server preflight documentation verification

Changed file: `docs/server-preflight.md`

## Recorded output

```text
Provision a supported Linux host with at least 20 GB available on the root filesystem, synchronized time, Docker Engine with Compose v2, `age`, `rclone`, `curl`, and `flock`. There is no minimum total root-filesystem capacity.

stale_150_root_min_status=1
no stale 150GB/ROOT_MIN_GB wording
syntax_status=0
```

The stale scan was `rg -n '150 ?GB|ROOT_MIN_GB' docs scripts`; status 1 is the expected no-match result. Shell syntax validation was `timeout 15s bash -n scripts/*.sh tests/ops/*.sh` and exited 0.

DoneClaim: server preflight documentation now states only the approved 20GB available-space requirement and explicitly removes any total-capacity minimum.
